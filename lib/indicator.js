import St from 'gi://St';
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

import { brandGicon } from './icons.js';

export const UsageIndicator = GObject.registerClass(
    class UsageIndicator extends PanelMenu.Button {
        _init(extension, providerId) {
            const service = extension.services[providerId];
            super._init(0.5, `${service.provider.name} Usage Tracker`);
            this._extension = extension;
            this._settings = extension.settings;
            this.providerId = providerId;

            this._box = new St.BoxLayout({
                style_class: 'ai-panel-label',
                y_align: Clutter.ActorAlign.CENTER,
                reactive: false
            });
            this.add_child(this._box);

            this._icon = new St.Icon({
                style_class: 'system-status-icon',
                gicon: brandGicon(providerId, extension.path, service.provider.icon),
                icon_size: 16,
                reactive: false
            });
            this._label = new St.Label({
                text: service.provider.shortName,
                y_align: Clutter.ActorAlign.CENTER,
                reactive: false
            });

            this._box.add_child(this._icon);
            this._box.add_child(this._label);
            this.update();
        }

        update() {
            const service = this._extension.services[this.providerId];
            const snapshot = service.data;

            // The brand glyph is the provider's identity and is always shown.
            this._icon.visible = true;

            if (!snapshot) {
                this._label.text = service.provider.shortName;
                this._label.visible = true;
                this._icon.style = '';
                this._label.style = '';
                return;
            }

            const tightest = this._tightestWindow(snapshot);
            const remaining = tightest ? Math.round(tightest.remainingPercent) : 0;
            const used = tightest ? Math.round(tightest.usedPercent) : 0;
            const status = this._status(remaining);
            const mode = this._settings.displayMode;

            this._label.visible = mode !== 'compact';
            this._label.text = mode === 'percentage' ? `${used}%` : mode === 'compact' ? '' : `${remaining}%`;

            // Status is conveyed by the label color; the icon keeps its brand color.
            const color = this._color(status, service.provider.color);
            this._label.style = color ? `color: ${color};` : '';
            this._icon.style = '';
        }

        _tightestWindow(snapshot) {
            return snapshot.windows.reduce((tightest, window) => {
                if (!tightest) return window;
                return window.remainingPercent < tightest.remainingPercent ? window : tightest;
            }, null);
        }

        _status(remainingPercent) {
            if (remainingPercent > 50) return 'safe';
            if (remainingPercent > 20) return 'moderate';
            return 'critical';
        }

        _color(status, providerColor) {
            if (this._settings.colorMode === 'single') return this._settings.singleColor;
            if (this._settings.colorMode !== 'multi') return null;
            if (status === 'safe') return providerColor;
            if (status === 'moderate') return '#ff7800';
            return '#e01b24';
        }
    }
);
