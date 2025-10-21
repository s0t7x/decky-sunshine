import { ServerAPI } from "decky-frontend-lib";
import type { SunshineVersionInfo } from './types';
import { LOG_TAG } from "./constants";

class Backend {
    public serverAPI: ServerAPI | undefined

    public pair = async (pin: string, client_name: string): Promise<boolean> => {
        const result = await this.call<{ pin: string; client_name: string }, boolean>("pair", { pin, client_name });
        return result === true;
    };

    public isSunshineRunning = async (): Promise<boolean> => {
        const result = await this.call<boolean>("isSunshineRunning");
        return result === true;
    }

    public areCredentialsValid = async (): Promise<boolean | null> => {
        const result = await this.call<boolean>("areCredentialsValid");
        return result;
    }

    public setCredentials = async (username: string, password: string): Promise<boolean | null> => {
        const result = await this.call<{username: string, password: string}, boolean | null>(
            "setCredentials",
            {
                username,
                password
            }
        );
        return result;
    }

    public getCredentials = async (): Promise<{username: string, password: string} | null> => {
        const result = await this.call<{username: string, password: string} | null>("getCredentials");
        return result;
    }

    public startSunshine = async () : Promise<boolean> => {
        console.log(LOG_TAG, "should start")
        const result = await this.call<boolean>("startSunshine");
        return result === true;
    }

    public stopSunshine = async () : Promise<boolean> => {
        console.log(LOG_TAG, "should stop")
        const result = await this.call<boolean>("stopSunshine");
        return result === true;
    }

    public getSunshineVersionInfo = async (): Promise<SunshineVersionInfo | null> => {
        const result = await this.call<SunshineVersionInfo | null>("getSunshineVersionInfo");
        return result;
    }

    public updateSunshine = async (): Promise<boolean> => {
        const result = await this.call<boolean>("updateSunshine");
        return result === true;
    }

    private call<TRes>(method: string): Promise<TRes | null>;
    private call<TArgs, TRes>(method: string, args: TArgs): Promise<TRes | null>;
    private async call(method: string, args?: unknown): Promise<unknown | null>{
        if (!this.serverAPI) {
            console.error(LOG_TAG, "Server API not initialized");
            return null;
        }
        const res = await this.serverAPI.callPluginMethod(method, args as unknown);
        console.log(LOG_TAG, `Backend call ${method} result`, res);
        if (!res?.success) {
            console.error(LOG_TAG, `Backend method ${method} failed`, res?.result);
            return null;
        }
        return res.result;
    }
}
const backend = new Backend()
export default backend