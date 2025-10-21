<div align="center">
  <img height="220" width="auto" src="assets/Decky_Sunshine_Logo.png " alt="Decky Sunshine Logo" />
  <h1>Decky Sunshine</h1>
  <p>Stream your Steam Deck screen to another device with minimal effort.</p>
</div>

# Features
With Decky Sunshine you can:
- Install, set up, update, and launch the [Sunshine](https://app.lizardbyte.dev/Sunshine/) streaming server from Game Mode
- Pair another device running the [Moonlight](https://moonlight-stream.org/) app
- Start remote play with low latency

That’s it - easy streaming from your Steam Deck.

# Installation & Setup
Follow these steps to get Decky Sunshine installed and ready.

## Before You Start
Make sure:
1. You have [Decky Loader](https://decky.xyz) installed
2. Your Steam Deck and the other device are on the same Wi-Fi or local network
3. Sunshine is **not** already manually installed

## 1. Install the Plugin
1. Open the Quick Access Menu (press the "…" / three-dots button)
2. Go to the Decky tab (the plug symbol)
3. Open the Decky Plugin Store
4. Search for “Decky Sunshine”
5. Install it
6. Return to the Decky tab

The plugin will handle installing Sunshine automatically.

## 2. Start Sunshine
1. In the Decky tab, select **Decky Sunshine**
2. Ensure the status is **Running** (it should be **Running** after the initial install)
3. If it is **Stopped**, press `Start Sunshine`

## 3. Install Moonlight on Your Other Device
1. Install Moonlight from your device’s app store or [moonlight-stream.org](https://moonlight-stream.org/)
2. Open Moonlight on your device

## 4. Pair the Device

### Option A: Automatic Discovery
1. In Moonlight, your Steam Deck should appear automatically as **steamdeck** (based on your host name)
2. Select it
3. Moonlight will display a PIN

### Option B: Manual IP Entry
1. In Moonlight, choose **Add (PC / +)**
2. Enter your Steam Deck’s IP address
   *(find it under Steam Deck → Settings → Internet → (your network) → Details)*
3. Moonlight will display a PIN

### Complete Pairing on the Deck
1. On your Steam Deck, go to Decky → Decky Sunshine and press `Pair Client`
2. Enter a client name (any label, e.g. `LivingRoomTV`) and the PIN shown in Moonlight
3. Press `Pair` to confirm

## 5. Start Streaming
1. In Moonlight, select **Desktop**
2. Your Steam Deck interface will appear on the other device
3. Play as normal - inputs will be sent back to the Deck

# FAQs
### I have an issue / the plugin does not behave as expected.
1. First, check the other FAQ entries - your question may already be answered.
2. If not, search the open and closed issues to see if your problem has already been reported or solved.
2. Review the logs located at `/home/deck/homebrew/logs/decky-sunshine/`.
3. If you still can’t resolve the issue, open an issue and describe:
   - What happened vs. what you expected
   - Relevant log excerpts (attach or paste them)

### I manually installed Sunshine before. Can I still use Decky Sunshine?<a id="faq-installedBefore"></a>
This depends on how you ran Sunshine before. If you started Sunshine as root user (e.g. using `sudo -i flatpak run`), you should be able to login using the credentials you used in your initial setup. If this does not work, you could uninstall Sunshine and delete its configuration (this includes all paired devices!) using the command `flatpak uninstall --delete-data dev.lizardbyte.app.Sunshine`, and then let Decky Sunshine install and setup Sunshine. You could also try setting a username and password for the root user (see the [Sunshine documentation about forgotten credentials](https://docs.lizardbyte.dev/projects/sunshine/master/md_docs_2troubleshooting.html#forgotten-credentials)).

### Will you add feature X?
The goal of this plugin is to simplify setting up Sunshine in Game Mode and pairing Moonlight clients.
If your idea supports that, feel free to open an issue. Features outside this goal will probably not be implemented, since they take development time and ongoing maintenance.

### I want to change a setting in Sunshine. Will you add a feature for that?
If the setting improves the experience for many users, open an issue to discuss.
Otherwise, just adjust it in **Sunshine’s Web UI** using the credentials displayed after clicking the `Show credentials` button.

### How can I see the Steam overlays on my device while playing?
You can stream the Steam overlays (three-dots / "STEAM" button menus) by enabling a developer setting. This may cause visual or performance issues; revert if you notice problems.

1. Press the STEAM button.
2. Open Settings.
3. Under System, enable Developer Mode (a Developer tab appears at the end).
4. Open Developer.
5. Enable Force Composite.
6. Restart your stream if it is already running.

To undo this, disable Force Composite.

### The plugin asks for credentials.
If you manually installed Sunshine before, see [the related FAQ entry](#faq-installedBefore).
If you changed your Sunshine credentials e.g. from Sunshine's Web UI, enter these credentials.

### I want to install a nightly version. How can I do that?
To install a nightly (or specific) version:
1. Open the Decky tab and press the cog to open Decky Loader settings.
2. In General, enable Developer mode (under OTHER).
3. Open the new Developer tab.
4. Either:
    - Download the desired ZIP to your Steam Deck, then use Browse under Install Plugin from ZIP File, or
    - Enter the direct ZIP URL in Install Plugin from URL and press Install.

# Contributing
Ideas, issues, and improvements are welcome - open an issue or PR.

# Thanks
Thanks to the **Decky Loader**, **Sunshine**, and **Moonlight** projects for making this possible.
