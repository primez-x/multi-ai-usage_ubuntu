import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const PROVIDERS = {
    codex: { id: 'codex', name: 'Codex', shortName: 'Cx', icon: 'applications-engineering-symbolic', color: '#49a3b0' },
    claude: { id: 'claude', name: 'Claude', shortName: 'Cl', icon: 'applications-science-symbolic', color: '#d97757' },
    kimi: { id: 'kimi', name: 'Kimi', shortName: 'Ki', icon: 'applications-development-symbolic', color: '#fe603c' },
    glm: { id: 'glm', name: 'GLM', shortName: 'GLM', icon: 'applications-other-symbolic', color: '#4f7cff' },
};

const STATE_PATH = GLib.build_filenamev([GLib.get_home_dir(), '.cache', 'ai-usage-tracker', 'state.json']);
const HELPER_PATH = GLib.build_filenamev([
    GLib.get_home_dir(),
    '.local',
    'share',
    'gnome-shell',
    'extensions',
    'ai-usage-tracker@local',
    'bin',
    'ai_usage_tracker_helper.py',
]);

export function providerDefinitions() {
    return PROVIDERS;
}

export function statePath() {
    return STATE_PATH;
}

function parseDate(value) {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

function clampPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(100, number));
}

function normalizeWindow(window) {
    if (!window || !window.label) return null;
    const usedPercent = clampPercent(window.usedPercent);
    const remainingPercent = window.remainingPercent === undefined
        ? Math.max(0, 100 - usedPercent)
        : clampPercent(window.remainingPercent);
    return {
        label: String(window.label),
        usedPercent,
        remainingPercent,
        windowMinutes: window.windowMinutes ?? null,
        resetsAt: parseDate(window.resetsAt),
        detail: window.detail ?? null,
    };
}

function waitForProcess(process) {
    return new Promise((resolve, reject) => {
        process.wait_check_async(null, (proc, result) => {
            try {
                proc.wait_check_finish(result);
                resolve();
            } catch (e) {
                reject(e);
            }
        });
    });
}

export function loadCachedState() {
    const file = Gio.File.new_for_path(STATE_PATH);
    if (!file.query_exists(null)) return null;

    const [ok, contents] = file.load_contents(null);
    if (!ok) return null;

    const text = new TextDecoder('utf-8').decode(contents);
    const state = JSON.parse(text);
    if (state?.schemaVersion !== 1 || typeof state.providers !== 'object') return null;
    return state;
}

export async function startHelperService() {
    const process = Gio.Subprocess.new(
        ['systemctl', '--user', 'start', 'ai-usage-tracker.service'],
        Gio.SubprocessFlags.NONE
    );
    await waitForProcess(process);
}

export async function runHelperOnce(providerId = null) {
    const argv = ['/usr/bin/python3', HELPER_PATH];
    if (providerId) argv.push('--provider', providerId);

    const process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
    await waitForProcess(process);
}

export class CachedProviderService {
    constructor(provider) {
        this.provider = provider;
        this.data = null;
        this.lastError = 'Waiting for background refresh.';
    }

    applyState(providerState) {
        if (!providerState) {
            this.data = null;
            this.lastError = 'Waiting for background refresh.';
            return;
        }

        const windows = (providerState.windows || []).map(normalizeWindow).filter(Boolean);
        this.data = windows.length ? {
            provider: this.provider,
            source: providerState.source ?? null,
            updatedAt: parseDate(providerState.updatedAt) || new Date(),
            windows,
            credits: providerState.credits ?? null,
            plan: providerState.plan ?? null,
        } : null;
        this.lastError = providerState.error || null;
    }

    async refresh() {
        await runHelperOnce(this.provider.id);
    }

    destroy() {
    }
}
