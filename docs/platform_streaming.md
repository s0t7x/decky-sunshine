# Streaming Gameplay to Platforms like Twitch

This guide will walk you through the steps to stream your Steam Deck gameplay to platforms like Twitch using the Decky Sunshine Plugin and Open Broadcaster Software (OBS).

## Installing Decky

1. Access the Decky website (https://decky.xyz) from your Steam Deck and download the installer.
2. If your browser cannot run files, open the downloaded installer from the Dolphin file manager.

## Installing Decky Sunshine Plugin

1. Download the latest ZIP from [releases](https://github.com/s0t7x/decky-sunshine/releases/latest).
2. Open the Quick Access Menu navigate to Decky and click the Gear-Icon in the top-right corner to open Decky's settings.
3. In "General" enable "Developer Settings" and navigate to the "Developer" tab.
4. Click on "Install from ZIP" and select the `Decky.Sunshine.zip` file.
5. The plugin will now be installed and accessible from the Quick Access Menu.

## Starting the Sunshine Server

1. In the Decky tab of the Quick Access Menu, locate the Decky Sunshine Plugin and click on the toggle button to enable the Sunshine server.

## Installing Moonlight Client on a Windows PC

1. Download the Moonlight Desktop Client for Windows from the official website (https://moonlight-stream.org/).
2. Run the installer and follow the on-screen instructions to complete the installation.

## Pairing the Moonlight Client with the Sunshine Server

1. Launch the Moonlight Desktop Client on your Windows PC.
2. You may wait till your Sunshine Server is located or add its IP manually.
3. Select your Steam Deck.
4. On your Steam Deck navigate to Decky Sunshine in the Quick Access Menu.
5. Enter the PIN displayed on your PC and click on "Pair".
6. Once paired, the Moonlight Client will connect to the Sunshine server and stream your Steam Deck.

## Setting up OBS for Streaming

1. Download and install OBS Studio from the official website (https://obsproject.com/).
2. Launch OBS and create a new scene.
3. In the "Sources" panel, click on the "+" button and select "Game Capture".
4. In the "Create/Select Source" window, choose the Moonlight Desktop Client from the list of running applications.
5. Configure the settings as desired and click "OK" to add the game capture source to your scene.
6. In the "Audio Mixer" panel, ensure that the Moonlight Desktop Client is selected as an audio source.

## Streaming to Twitch

1. In OBS, navigate to the "Settings" menu and select the "Stream" option.
2. Choose "Twitch" as the streaming service and enter your Twitch stream key.
3. Configure any additional settings as desired.
4. When ready, click the "Start Streaming" button in OBS to begin streaming your Steam Deck gameplay to Twitch.

With these steps, you should now be able to stream your Steam Deck gameplay to platforms like Twitch using the Decky Sunshine Plugin, Moonlight Desktop Client, and OBS. Remember to adjust settings and configurations as needed for optimal streaming performance.
