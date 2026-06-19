import St from 'gi://St';
import Clutter from 'gi://Clutter';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import { brandGicon } from './icons.js';
import { formatResetTime } from './time.js';

export class UsageMenuBuilder {
    constructor(indicator, extension) {
        this._indicator = indicator;
        this._extension = extension;
    }

    build() {
        const menu = this._indicator.menu;
        menu.removeAll();
        const service = this._extension.services[this._indicator.providerId];
        this._buildHeader(menu, service);
        this._buildUsage(menu, service);
        this._buildFooter(menu, service);
    }

    _buildHeader(menu, service) {
        const headerBox = new St.BoxLayout({ style_class: 'ai-usage-header' });
        headerBox.add_child(new St.Icon({
            gicon: brandGicon(service.provider.id, this._extension.path, service.provider.icon),
            icon_size: 20,
            y_align: Clutter.ActorAlign.CENTER
        }));
        headerBox.add_child(new St.Label({
            text: service.provider.name,
            style_class: 'ai-title',
            y_align: Clutter.ActorAlign.CENTER
        }));
        headerBox.add_child(new St.Widget({ x_expand: true }));

        const refreshBtn = new St.Button({ style_class: 'ai-button' });
        refreshBtn.child = new St.Icon({ icon_name: 'view-refresh-symbolic', icon_size: 14 });
        refreshBtn.connect('clicked', () => this._extension.refreshProvider(service.provider.id));
        headerBox.add_child(refreshBtn);

        const settingsBtn = new St.Button({ style_class: 'ai-button' });
        settingsBtn.child = new St.Icon({ icon_name: 'emblem-system-symbolic', icon_size: 14 });
        settingsBtn.connect('clicked', () => {
            this._indicator.menu.close();
            this._extension.openPreferences();
        });
        headerBox.add_child(settingsBtn);

        const headerItem = new PopupMenu.PopupBaseMenuItem({ reactive: false });
        headerItem.remove_style_class_name('popup-inactive-menu-item');
        headerItem.add_child(headerBox);
        menu.addMenuItem(headerItem);
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        if (service.lastError) {
            const errorItem = new PopupMenu.PopupBaseMenuItem({ reactive: false });
            errorItem.add_child(new St.Label({ text: service.lastError, style_class: 'ai-error-banner' }));
            menu.addMenuItem(errorItem);
        }
    }

    _buildUsage(menu, service) {
        const snapshot = service.data;
        if (!snapshot || !snapshot.windows.length) {
            const emptyItem = new PopupMenu.PopupBaseMenuItem({ reactive: false });
            emptyItem.add_child(new St.Label({ text: 'No usage data available.' }));
            menu.addMenuItem(emptyItem);
            return;
        }

        for (const window of snapshot.windows) this._addWindow(menu, window);
    }

    _addWindow(menu, window) {
        const item = new PopupMenu.PopupBaseMenuItem({ reactive: false });
        const box = new St.BoxLayout({ vertical: true, x_expand: true });
        const row = new St.BoxLayout();
        row.add_child(new St.Label({
            text: window.label,
            style_class: 'ai-usage-label',
            y_align: Clutter.ActorAlign.CENTER
        }));
        row.add_child(new St.Widget({ x_expand: true }));

        const status = this._status(window.remainingPercent);
        row.add_child(new St.Label({
            text: `${Math.round(window.remainingPercent)}% left`,
            style_class: `ai-usage-value ai-status-${status}`
        }));
        box.add_child(row);

        const progressBox = new St.BoxLayout({ style_class: 'ai-progress-bar' });
        progressBox.add_child(new St.Widget({
            style_class: `ai-progress-fill ${status}`,
            width: Math.max(2, Math.round((window.usedPercent / 100) * 180))
        }));
        box.add_child(progressBox);

        box.add_child(new St.Label({
            text: window.detail || `${Math.round(window.usedPercent)}% used`,
            style_class: 'ai-reset-time'
        }));

        if (window.resetsAt) {
            box.add_child(new St.Label({
                text: formatResetTime(window.resetsAt, this._extension.settings.resetDisplayMode),
                style_class: 'ai-reset-time'
            }));
        }

        item.add_child(box);
        menu.addMenuItem(item);
    }

    _buildFooter(menu, service) {
        const snapshot = service.data;
        if (!snapshot) return;
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const details = [];
        if (snapshot.plan) details.push(`Plan: ${snapshot.plan}`);
        if (snapshot.source) details.push(`Source: ${snapshot.source}`);
        if (snapshot.credits !== null && snapshot.credits !== undefined) details.push(`Credits: ${snapshot.credits}`);
        details.push(`Updated ${this._timeUntil(new Date(snapshot.updatedAt))}`);

        for (const detail of details) {
            const item = new PopupMenu.PopupBaseMenuItem({ reactive: false });
            item.add_child(new St.Label({ text: detail, style_class: 'ai-reset-time' }));
            menu.addMenuItem(item);
        }
    }

    _status(remainingPercent) {
        if (remainingPercent > 50) return 'safe';
        if (remainingPercent > 20) return 'moderate';
        return 'critical';
    }

    _timeUntil(date) {
        const seconds = Math.floor((date - new Date()) / 1000);
        const abs = Math.abs(seconds);
        if (abs < 60) return seconds >= 0 ? 'soon' : 'just now';
        const prefix = seconds >= 0 ? 'in ' : '';
        const minutes = Math.floor(abs / 60);
        if (minutes < 60) return `${prefix}${minutes}m`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${prefix}${hours}h`;
        return `${prefix}${Math.floor(hours / 24)}d`;
    }
}
