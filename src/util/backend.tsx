import { ServerAPI } from "decky-frontend-lib";

class Backend {
    public serverAPI: ServerAPI | undefined

    public sunshineSendPin = async (pin: string): Promise<boolean> => {
        const result = await this.serverAPI?.callPluginMethod<{ pin: string }, boolean>(
            "sendPin",
            { pin }
        );
        console.log("[SUN]", "sendPin result", result)
        return Boolean(result?.result || false)
    }

    public sunshineIsRunning = async () => {
        const result = await this.serverAPI?.callPluginMethod<any, boolean>(
            "sunshineIsRunning",
            {}
        );
        console.log("[SUN]", "sunshineCheckRunning result", result)
        if (result?.result) {
            return true
        } else {
            return false
        }
    };

    public sunshineSetAuthHeader = async (username: string, password: string): Promise<boolean> => {
        const result = await this.serverAPI?.callPluginMethod<any, boolean>(
            "setAuthHeader",
            {
                username,
                password
            }
        );
        console.log("[SUN]", "setAuthHeader result", result)
        return Boolean(result?.result || false)
    }

    public sunshineIsAuthorized = async (): Promise<boolean> => {
        if (!this.sunshineIsRunning()) return false
        const result = await this.serverAPI?.callPluginMethod<any, boolean>(
            "sunshineIsAuthorized",
            {}
        );
        console.log("[SUN]", "sunshineCheckAuthorized result", result)
        if (result?.success) {
            return Boolean(result?.result || false);
        } else {
            return false;
        }
    };

    public sunshineStart = async () => {
        console.log("[SUN]", "should start")
        let result = await this.serverAPI?.callPluginMethod<any, any>(
            "sunshineStart",
            {}
        )
        console.log("[SUN] start res: ", result)
        return Boolean(result?.result || false)
    }

    public sunshineStop = async () => {
        console.log("[SUN]", "should stop")
        let result = await this.serverAPI?.callPluginMethod<any, any>(
            "sunshineStop",
            {}
        )
        console.log("[SUN] stop res: ", result)
        return Boolean(result?.result || false)
    }

    public sunshineSetUser = async (
        newUsername: string,
        newPassword: string,
        confirmNewPassword: string,
        currentUsername: string | undefined,
        currentPassword: string | undefined,
    ) => {
        console.log("[SUN]", "Set User")
        let namedParams =  {
            newUsername,
            newPassword,
            confirmNewPassword
        } as any
        if(currentUsername || currentPassword) {
            namedParams.currentUsername = currentUsername
            namedParams.currentPassword = currentPassword
        }
        let result = await this.serverAPI?.callPluginMethod<any, any>(
            "sunshineSetUser",
           namedParams
        )
        console.log("[SUN] setUser res: ", result)
        return Boolean(result?.result || false)
    }
}
const backend = new Backend()
export default backend