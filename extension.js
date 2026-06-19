import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

import { ExtensionSettings } from './lib/settings.js';
import { CachedProviderService, loadCachedState, providerDefinitions, runHelperOnce, startHelperService, statePath } from './lib/apiService.js';
import { UsageIndicator } from './lib/indicator.js';
import { UsageMenuBuilder } from './lib/menu.js';
import { clearBrandIconCache } from './lib/icons.js';

export default class AIUsageExtension extends Extension {
    enable() {
        this.settings = new ExtensionSettings(this.getSettings());
        this.providerDefs = providerDefinitions();
        this.services = {};
        this._indicators = new Map();
        this._menuBuilders = new Map();
        this._menuOpenIds = new Map();
        this._cacheMonitor = null;
        this._cacheMonitorId = null;
        this._stateReloadId = null;

        for (const [id, provider] of Object.entries(this.providerDefs)) {
            this.services[id] = new CachedProviderService(provider);
        }

        this._migrateProviderSettings();

        this._settingsSignals = [];
        this._settingsSignals.push(this.settings.connectSignal('refresh-interval', () => this._restartTimer()));
        this._settingsSignals.push(this.settings.connectSignal('display-mode', () => this._updateIndicators()));
        this._settingsSignals.push(this.settings.connectSignal('reset-display-mode', () => this._rebuildOpenMenus()));
        this._settingsSignals.push(this.settings.connectSignal('color-mode', () => this._updateIndicators()));
        this._settingsSignals.push(this.settings.connectSignal('single-color', () => this._updateIndicators()));
        this._settingsSignals.push(this.settings.connectSignal('enabled-providers', () => {
            this._rebuildIndicators();
            this._syncFromCache();
            this.refresh();
        }));
        this._settingsSignals.push(this.settings.connectSignal('provider-order', () => this._rebuildIndicators()));

        this._rebuildIndicators();
        this._startCacheMonitor();
        this._syncFromCache();
        this._startTimer();
        this._ensureHelperRunning();
        this.refresh();
    }

    disable() {
        this._stopTimer();
        this._stopCacheMonitor();
        this._clearScheduledReload();
        this._destroyIndicators();

        for (const id of this._settingsSignals) {
            this.settings.disconnectSignal(id);
        }
        this._settingsSignals = [];

        for (const service of Object.values(this.services)) {
            service.destroy();
        }
        this.services = {};
        this._indicators = null;
        this._menuBuilders = null;
        this._menuOpenIds = null;
        clearBrandIconCache();
        this.settings = null;
    }

    /**
     * Surface newly-introduced providers without disturbing existing choices.
     *
     * Any provider id present in the code but absent from BOTH the user's
     * enabled list and their order list is brand new (never seen by this
     * install): enable and order it once. Providers the user has explicitly
     * disabled remain disabled, because they still appear in one of the lists.
     * Also prunes stale ids and back-fills the order for enabled-but-unordered
     * providers so every enabled indicator can render.
     */
    _migrateProviderSettings() {
        const known = Object.keys(this.providerDefs);
        const enabled = new Set(this.settings.enabledProviders.filter(id => known.includes(id)));
        const order = this.settings.providerOrder.filter(id => known.includes(id));
        const seen = new Set([...enabled, ...order]);

        const newOrder = [...order];
        let enabledChanged = enabled.size !== this.settings.enabledProviders.length;
        let orderChanged = newOrder.length !== this.settings.providerOrder.length;

        for (const id of known) {
            if (!seen.has(id)) {
                enabled.add(id);
                newOrder.push(id);
                enabledChanged = true;
                orderChanged = true;
            } else if (!newOrder.includes(id)) {
                newOrder.push(id);
                orderChanged = true;
            }
        }

        if (enabledChanged)
            this.settings.setEnabledProviders([...enabled]);
        if (orderChanged)
            this.settings.setProviderOrder(newOrder);
    }

    async refresh() {
        try {
            await runHelperOnce();
        } catch (e) {
            log(`AIUsage: background refresh failed: ${e.message}`);
        } finally {
            this._syncFromCache();
        }
    }

    async refreshProvider(providerId) {
        const service = this.services[providerId];
        if (!service) return;

        try {
            await service.refresh();
        } catch (e) {
            log(`AIUsage: ${providerId} refresh error: ${e.message}`);
        } finally {
            this._syncFromCache();
        }
    }

    _rebuildIndicators() {
        this._destroyIndicators();

        const enabled = new Set(this.settings.enabledProviders);
        const ordered = this.settings.providerOrder.filter(id => enabled.has(id) && this.services[id]);
        const missing = [...enabled].filter(id => !ordered.includes(id) && this.services[id]);

        for (const providerId of [...ordered, ...missing]) {
            const indicator = new UsageIndicator(this, providerId);
            const builder = new UsageMenuBuilder(indicator, this);
            builder.build();

            const role = `ai-usage-tracker-${providerId}`;
            this._removeStaleStatusAreaRole(role);
            Main.panel.addToStatusArea(role, indicator);

            const manager = new PopupMenu.PopupMenuManager(indicator);
            manager.addMenu(indicator.menu);
            indicator._aiUsageMenuManager = manager;

            const openId = indicator.menu.connect('open-state-changed', (menu, isOpen) => {
                if (isOpen) builder.build();
            });

            this._indicators.set(providerId, indicator);
            this._menuBuilders.set(providerId, builder);
            this._menuOpenIds.set(providerId, openId);
        }
    }

    _destroyIndicators() {
        if (!this._indicators) return;

        for (const [providerId, indicator] of this._indicators) {
            const openId = this._menuOpenIds.get(providerId);
            if (openId) indicator.menu.disconnect(openId);

            if (indicator._aiUsageMenuManager) {
                indicator._aiUsageMenuManager.removeMenu(indicator.menu);
                indicator._aiUsageMenuManager = null;
            }

            indicator.destroy();
            const role = `ai-usage-tracker-${providerId}`;
            if (Main.panel.statusArea[role] === indicator)
                Main.panel.statusArea[role] = null;
        }
        this._indicators.clear();
        this._menuBuilders.clear();
        this._menuOpenIds.clear();
    }

    _removeStaleStatusAreaRole(role) {
        const indicator = Main.panel.statusArea[role];
        if (!indicator)
            return;

        try {
            indicator.destroy?.();
        } catch (e) {
            log(`AIUsage: failed to destroy stale status area role ${role}: ${e.message}`);
        }

        if (Main.panel.statusArea[role] === indicator)
            Main.panel.statusArea[role] = null;
    }

    _updateIndicators() {
        if (!this._indicators) return;

        for (const indicator of this._indicators.values()) {
            indicator.update();
        }
    }

    _rebuildOpenMenus() {
        if (!this._indicators) return;

        for (const [providerId, indicator] of this._indicators) {
            if (indicator.menu?.isOpen) this._menuBuilders.get(providerId)?.build();
        }
    }

    _syncFromCache() {
        if (!this.services) return;

        let state = null;
        try {
            state = loadCachedState();
        } catch (e) {
            log(`AIUsage: cache read error: ${e.message}`);
        }

        for (const [providerId, service] of Object.entries(this.services)) {
            service.applyState(state?.providers?.[providerId] ?? null);
        }

        this._updateIndicators();
        this._rebuildOpenMenus();
    }

    _scheduleCacheReload() {
        if (this._stateReloadId) return;

        this._stateReloadId = GLib.timeout_add(GLib.PRIORITY_LOW, 250, () => {
            this._stateReloadId = null;
            this._syncFromCache();
            return GLib.SOURCE_REMOVE;
        });
    }

    _clearScheduledReload() {
        if (!this._stateReloadId) return;

        GLib.source_remove(this._stateReloadId);
        this._stateReloadId = null;
    }

    _startCacheMonitor() {
        const file = Gio.File.new_for_path(statePath());
        try {
            this._cacheMonitor = file.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._cacheMonitorId = this._cacheMonitor.connect('changed', () => this._scheduleCacheReload());
        } catch (e) {
            log(`AIUsage: cache monitor error: ${e.message}`);
        }
    }

    _stopCacheMonitor() {
        if (!this._cacheMonitor) return;

        if (this._cacheMonitorId) {
            this._cacheMonitor.disconnect(this._cacheMonitorId);
            this._cacheMonitorId = null;
        }
        this._cacheMonitor.cancel();
        this._cacheMonitor = null;
    }

    _ensureHelperRunning() {
        startHelperService().catch(e => {
            log(`AIUsage: helper service start error: ${e.message}`);
        });
    }

    _startTimer() {
        const interval = Math.max(10, this.settings.refreshInterval);
        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_LOW, interval, () => {
            this._syncFromCache();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopTimer() {
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = null;
        }
    }

    _restartTimer() {
        this._stopTimer();
        this._startTimer();
    }
}
