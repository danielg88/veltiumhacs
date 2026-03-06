# Veltium EV Charger for Home Assistant

A custom integration for Home Assistant to monitor your Veltium EV Charger.

This integration fetches your entire charging history from the Veltium cloud and intelligently uses Home Assistant's Long-Term Statistics (`async_import_statistics`) to ensure that even if your charger was offline and synced data a week late, the energy consumption is plotted accurately on the exact day it occurred in the Energy Dashboard.

## Features

* **UI Configuration**: Easy setup directly from the Home Assistant interface.
* **Energy Dashboard Support**: Provides a Lifetime Energy sensor natively compatible with the Home Assistant Energy Dashboard (`total_increasing`).
* **Custom Graphing Sensors**: Provides Daily and Monthly energy sensors (`total`) that reset automatically, perfect for building custom bar charts in Lovelace.
* **Smart Historical Backfilling**: Never worry about offline/delayed Bluetooth syncs again. When data finally reaches the Veltium cloud, this integration pushes it back in time to the correct hour in Home Assistant's Long Term Statistics database.

## Installation 

### Option 1: HACS (Recommended)

1. Open Home Assistant and navigate to **HACS**.
2. Click on **Integrations**.
3. Click the three dots in the top right corner and select **Custom repositories**.
4. Paste the URL of this GitHub repository into the input field.
5. Select **Integration** as the category and click **Add**.
6. Close the modal, search for "Veltium" in HACS, and click **Download**.
7. Restart Home Assistant.

### Option 2: Manual Installation

1. Download the `custom_components/veltium` folder from this repository.
2. Copy the folder into your Home Assistant's `config/custom_components/` directory.
3. Restart Home Assistant.

## Configuration

1. In Home Assistant, go to **Settings** -> **Devices & Services**.
2. Click **+ Add Integration** in the bottom right corner.
3. Search for "Veltium".
4. Enter your:
   * **Email**: The email address you use for the Veltium App.
   * **Password/PIN**: Your Veltium App password or PIN.
   * **Firebase API Key**: The Google Cloud Web API Key used by the Veltium app.
5. Click **Submit**.

> **Note**: The integration polls the Veltium API once per day. The first time you set it up, it will take a moment to backfill all your historical data. Wait an hour for Home Assistant's Energy Dashboard to process the newly injected statistics.
