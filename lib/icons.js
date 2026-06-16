import Gio from 'gi://Gio';

// GIcons are immutable and safe to share across actors; cache so repeated
// indicator updates and menu rebuilds don't keep re-reading the SVG file.
const _cache = new Map();

/**
 * Return a GIcon for a provider's brand mark.
 *
 * Prefers a bundled SVG at `<extensionDir>/icons/<id>.svg` (a real brand glyph
 * rendered in the provider's color). Falls back to the provider's symbolic
 * icon name when no bundled SVG exists, so the extension degrades gracefully.
 *
 * @param {string} providerId          provider id, e.g. "claude"
 * @param {string} extensionDir        absolute path to the extension directory
 * @param {string} fallbackIconName    themed icon name used if no SVG is bundled
 * @returns {Gio.Icon}
 */
export function brandGicon(providerId, extensionDir, fallbackIconName) {
    const cacheKey = `${extensionDir}::${providerId}`;
    const cached = _cache.get(cacheKey);
    if (cached)
        return cached;

    const file = Gio.File.new_for_path(`${extensionDir}/icons/${providerId}.svg`);
    const gicon = file.query_exists(null)
        ? new Gio.FileIcon({ file })
        : new Gio.ThemedIcon({ name: fallbackIconName || 'application-x-executable-symbolic' });

    _cache.set(cacheKey, gicon);
    return gicon;
}

/** Drop the cache (used on disable so a re-enable picks up changed SVGs). */
export function clearBrandIconCache() {
    _cache.clear();
}
