# Streaming Gameplay to Platforms like Twitch

This guide will shortly summarize [Getting Started with Decky Sunshine](https://github.com/s0t7x/decky-sunshine/blob/main/docs/getting_started.md) and explain further steps to stream your Steam Deck gameplay to platforms like Twitch using Open Broadcaster Software (OBS) on your PC.

## Prepare Streaming

On your Steam Deck:

1. Make sure [Decky Plugin Loader](https://decky.xyz) is installed
2. Download and install Decky Sunshine
3. Enable the Sunshine Server
   
On your PC:

1. Download and install the Moonlight Desktop Client
2. In the Moonlight Client Select your Steam Deck.
3. On your Steam Deck navigate to Decky Sunshine in the Quick Access Menu.
4. Enter the PIN displayed on your PC and click on "Pair".
5. Once paired, the Moonlight Client will connect to the Sunshine server and stream your Steam Deck.

For a detailed guide on how to install Decky Sunshine take a look at [Getting Started with Decky Sunshine](https://github.com/s0t7x/decky-sunshine/blob/main/docs/getting_started.md).

## Setting up OBS for Streaming

1. Download and install OBS Studio from the [official website](https://obsproject.com/).
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
