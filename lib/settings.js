export class ExtensionSettings {
    constructor(settings) {
        this._settings = settings;
    }

    get refreshInterval() {
        return this._settings.get_int('refresh-interval');
    }

    get displayMode() {
        return this._settings.get_string('display-mode');
    }

    get resetDisplayMode() {
        return this._settings.get_string('reset-display-mode');
    }

    get colorMode() {
        return this._settings.get_string('color-mode');
    }

    get singleColor() {
        return this._settings.get_string('single-color');
    }

    get enabledProviders() {
        return this._settings.get_strv('enabled-providers');
    }

    get providerOrder() {
        return this._settings.get_strv('provider-order');
    }

    setEnabledProviders(ids) {
        this._settings.set_strv('enabled-providers', ids);
    }

    setProviderOrder(ids) {
        this._settings.set_strv('provider-order', ids);
    }

    connectSignal(key, callback) {
        return this._settings.connect(`changed::${key}`, callback);
    }

    disconnectSignal(id) {
        this._settings.disconnect(id);
    }
}
