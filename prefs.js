import Gtk from 'gi://Gtk';
import Gdk from 'gi://Gdk';
import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const PROVIDERS = [
    ['codex', 'Codex'],
    ['claude', 'Claude'],
    ['kimi', 'Kimi'],
    ['glm', 'GLM (Z.ai)'],
];

export default class AIUsagePreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();

        const page = new Adw.PreferencesPage({ title: 'Settings', icon_name: 'preferences-system-symbolic' });
        page.add(this._buildProviderGroup(settings));
        page.add(this._buildPanelGroup(settings));
        window.add(page);
    }

    _buildProviderGroup(settings) {
        const group = new Adw.PreferencesGroup({ title: 'Providers' });

        for (const [id, title] of PROVIDERS) {
            const row = new Adw.SwitchRow({
                title,
                subtitle: this._providerSubtitle(id),
            });
            row.active = settings.get_strv('enabled-providers').includes(id);
            row.connect('notify::active', () => {
                const enabled = new Set(settings.get_strv('enabled-providers'));
                if (row.active) enabled.add(id);
                else enabled.delete(id);
                settings.set_strv('enabled-providers', PROVIDERS.map(([providerId]) => providerId).filter(providerId => enabled.has(providerId)));
            });
            group.add(row);
        }

        return group;
    }

    _buildPanelGroup(settings) {
        const group = new Adw.PreferencesGroup({ title: 'Panel Indicator' });

        const intervalRow = new Adw.SpinRow({
            title: 'Refresh Interval',
            subtitle: 'Seconds between refreshes',
            adjustment: new Gtk.Adjustment({
                lower: 10,
                upper: 3600,
                step_increment: 10,
                value: settings.get_int('refresh-interval')
            })
        });
        settings.bind('refresh-interval', intervalRow, 'value', Gio.SettingsBindFlags.DEFAULT);
        group.add(intervalRow);

        const displayRow = new Adw.ComboRow({
            title: 'Display Mode',
            model: new Gtk.StringList({ strings: ['Remaining', 'Percentage Used', 'Compact'] })
        });
        const modeMap = ['remaining', 'percentage', 'compact'];
        displayRow.connect('notify::selected', () => {
            settings.set_string('display-mode', modeMap[displayRow.selected]);
        });
        const currentMode = settings.get_string('display-mode');
        displayRow.selected = Math.max(0, modeMap.indexOf(currentMode));
        group.add(displayRow);

        const resetDisplayRow = new Adw.ComboRow({
            title: 'Reset Display',
            model: new Gtk.StringList({ strings: ['Countdown', 'Expiration time'] })
        });
        const resetModeMap = ['countdown', 'time'];
        resetDisplayRow.connect('notify::selected', () => {
            settings.set_string('reset-display-mode', resetModeMap[resetDisplayRow.selected]);
        });
        const currentResetMode = settings.get_string('reset-display-mode');
        resetDisplayRow.selected = Math.max(0, resetModeMap.indexOf(currentResetMode));
        group.add(resetDisplayRow);

        const colorRow = new Adw.ComboRow({
            title: 'Color Mode',
            model: new Gtk.StringList({ strings: ['Multi-color', 'Single color', 'Off'] })
        });
        const colorMap = ['multi', 'single', 'off'];
        colorRow.connect('notify::selected', () => {
            settings.set_string('color-mode', colorMap[colorRow.selected]);
        });
        const currentColor = settings.get_string('color-mode');
        colorRow.selected = Math.max(0, colorMap.indexOf(currentColor));
        group.add(colorRow);

        const colorBtn = new Gtk.ColorButton({
            valign: Gtk.Align.CENTER,
            use_alpha: false
        });
        const rgba = new Gdk.RGBA();
        rgba.parse(settings.get_string('single-color'));
        colorBtn.set_rgba(rgba);
        colorBtn.connect('color-set', () => {
            const c = colorBtn.get_rgba();
            const hex = `#${Math.round(c.red * 255).toString(16).padStart(2, '0')}${Math.round(c.green * 255).toString(16).padStart(2, '0')}${Math.round(c.blue * 255).toString(16).padStart(2, '0')}`;
            settings.set_string('single-color', hex);
        });
        const colorEntryRow = new Adw.ActionRow({ title: 'Single Color', activatable_widget: colorBtn });
        colorEntryRow.add_suffix(colorBtn);
        group.add(colorEntryRow);

        return group;
    }

    _providerSubtitle(id) {
        switch (id) {
            case 'codex':
                return 'Codex session-log scan (no subprocess)';
            case 'claude':
                return 'Claude OAuth usage endpoint';
            case 'kimi':
                return 'Kimi coding usage API';
            case 'glm':
                return 'Z.ai GLM Coding Plan usage (uses ZAI_API_KEY or Claude Code z.ai config)';
            default:
                return '';
        }
    }
}
