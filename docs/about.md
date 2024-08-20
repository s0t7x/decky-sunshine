# About

This document provides an overview of the different components involved in the Decky Sunshine Plugin and how they work together.

## Decky Plugin Loader (Decky Loader)

Decky Plugin Loader is an open-source project written in Python with the goal of adding plugin-loading capabilities to the Steam Deck. After installing, plugins can be accessed using a plugins tab in the quick access menu. It serves as a platform for developers to create and distribute plugins that extend the functionality of the Steam Deck.

## A Decky Plugin

The Decky Sunshine Plugin is a plugin specifically designed to work with the Decky Plugin Loader. It provides a user-friendly interface for controlling the Sunshine game streaming server directly from the Steam Deck's interface.

## Sunshine (Open Source Moonlight Game Streaming Server)

Sunshine is an open-source implementation of the Moonlight game streaming server, which allows you to stream games from your Steam Deck to other devices over a local network or the internet. It is based on the GameStream protocol developed by NVIDIA.

## Moonlight (Game Streaming Protocol by NVIDIA)

Moonlight is a game streaming protocol developed by NVIDIA that enables low-latency, high-performance game streaming from compatible devices to other devices on the same network or over the internet. It is designed to provide a seamless gaming experience by efficiently encoding and transmitting video and audio data.

## Moonlight Desktop Client

The Moonlight Desktop Client is a software application that allows you to connect to and stream games from a Moonlight-compatible server, such as Sunshine. It runs on various platforms, including Windows, macOS, and Linux, and provides a user interface for connecting to the streaming server, managing game streaming sessions, and configuring settings.

## How Sunshine (Server) and Desktop Client Work Together

Sunshine and the Moonlight Desktop Client work together to enable game streaming from the Steam Deck to other devices. Here's how the process works:

1. **Sunshine Server**: The Sunshine server runs on your Steam Deck and captures the game's video and audio output in real-time.

2. **Encoding and Streaming**: Sunshine encodes the captured data using the Moonlight game streaming protocol and streams it over the network.

3. **Moonlight Desktop Client**: The Moonlight Desktop Client, running on another device (e.g., a desktop computer, laptop, or mobile device), connects to the Sunshine server and receives the encoded video and audio stream.

4. **Decoding and Rendering**: The Moonlight Desktop Client decodes the received stream and renders the game's video and audio on the target device, allowing you to play the game remotely as if it were running locally.

5. **Input Handling**: The Moonlight Desktop Client also handles input from the target device (e.g., keyboard, mouse, or gamepad) and sends it back to the Sunshine server, which then injects the input into the game running on the Steam Deck.

By leveraging the Decky Sunshine Plugin, you can easily control the Sunshine server, enabling or disabling game streaming as needed, without having to navigate through complex menus or command-line interfaces. The plugin provides a convenient way to manage your game streaming sessions directly from the Steam Deck's interface.
