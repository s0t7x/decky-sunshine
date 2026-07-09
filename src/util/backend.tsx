import { call } from "@decky/api";
import type { SunshineVersionInfo } from './types';
import { LOG_TAG } from "./constants";

class Backend {
    public pair = async (pin: string, clientName: string): Promise<boolean> => {
        const result = await this.call<[pin: string, clientName: string], boolean>("pair", pin, clientName);
        return result === true;
    };

    public isSunshineRunning = async (): Promise<boolean> => {
        const result = await this.call<[], boolean>("is_sunshine_running");
        return result === true;
    }

    public areCredentialsValid = async (): Promise<boolean | null> => {
        const result = await this.call<[], boolean | null>("are_credentials_valid");
        return result;
    }

    public setCredentials = async (username: string, password: string): Promise<boolean | null> => {
        const result = await this.call<[username: string, password: string], boolean | null>(
            "set_credentials",
            username,
            password
        );
        return result;
    }

    public getCredentials = async (): Promise<{username: string, password: string} | null> => {
        const result = await this.call<[], {username: string, password: string} | null>("get_credentials");
        return result;
    }

    public startSunshine = async () : Promise<boolean> => {
        console.log(LOG_TAG, "should start")
        const result = await this.call<[], boolean>("start_sunshine");
        return result === true;
    }

    public stopSunshine = async () : Promise<boolean> => {
        console.log(LOG_TAG, "should stop")
        const result = await this.call<[], boolean>("stop_sunshine");
        return result === true;
    }

    public getSunshineVersionInfo = async (refreshAppstream: boolean): Promise<SunshineVersionInfo | null> => {
        const result = await this.call<[refreshAppstream: boolean], SunshineVersionInfo | null>(
            "get_sunshine_version_info",
            refreshAppstream
        );
        return result;
    }

    public updateSunshine = async (): Promise<boolean> => {
        const result = await this.call<[], boolean>("update_sunshine");
        return result === true;
    }

    public getForceComposition = async (): Promise<boolean> => {
        const result = await this.call<[], boolean>("get_force_composition");
        return result === true;
    }

    public setForceComposition = async (enabled: boolean): Promise<boolean> => {
        const result = await this.call<[enabled: boolean], boolean>("set_force_composition", enabled);
        return result === true;
    }

    // Preserves the pre-@decky/api error contract: a failed backend call is
    // logged and mapped to null instead of throwing, so callers can keep
    // treating null/false as "failed".
    private async call<Args extends any[], TRes>(method: string, ...args: Args): Promise<TRes | null> {
        try {
            return await call<Args, TRes>(method, ...args);
        } catch (error) {
            console.error(LOG_TAG, `Backend method ${method} failed`, error);
            return null;
        }
    }
}
const backend = new Backend()
export default backend
