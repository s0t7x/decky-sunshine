export interface SunshineVersionInfo {
    current_version: string | null;
    // Set independently of update_version, which stays null when the remote
    // has no version string to offer. Key the update UI off this, not off it.
    update_available: boolean;
    update_version: string | null;
}

export interface WebUiInfo {
    ip: string | null;
    editing_ready: boolean;
}