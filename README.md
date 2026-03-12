# Veltium EV Charger for Home Assistant

A custom integration for Home Assistant to monitor your Veltium EV Charger.

This integration fetches your entire charging history from the Veltium cloud and intelligently uses Home Assistant's Long-Term Statistics (`async_import_statistics`) to ensure that even if your charger was offline and synced data a week late, the energy consumption is plotted accurately on the exact day it occurred in the Energy Dashboard.

## Features

* **UI Configuration**: Easy setup directly from the Home Assistant interface.
* **Energy Dashboard Support**: Provides a Lifetime Energy sensor natively compatible with the Home Assistant Energy Dashboard (`total_increasing`).
* **Custom Graphing Sensors**: Provides Daily and Monthly energy sensors (`total`) that reset automatically, perfect for building custom bar charts in Lovelace.
* **Smart Historical Backfilling**: Never worry about offline/delayed Bluetooth syncs again. When data finally reaches the Veltium cloud, this integration pushes it back in time to the correct hour in Home Assistant's Long Term Statistics database.
* **WebSocket Data API**: Exposes a custom WebSocket command (`veltium/ws/consumptions`) so complex Lovelace cards (like ApexCharts) can instantly query aggregated historical data (daily, weekly, monthly) directly from the statistics database without bulky client-side JavaScript.

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

## Advanced Graphing (ApexCharts)

Because Veltium injects all charge sessions natively into Home Assistant's Long-Term Statistics database, you can use the integration's built-in WebSocket command to easily plot beautiful long-term historical charts.

Here is an example of a monthly energy consumption bar chart using the popular [ApexCharts Card](https://github.com/RomRider/apexcharts-card):

```yaml
type: custom:apexcharts-card
graph_span: 1y
header:
  show: true
  title: Monthly Charging Energy (1 Year)
series:
  - entity: sensor.veltium_<your_device_id>_total_energy
    name: Energy
    type: column
    data_generator: |
      return hass.connection.sendMessagePromise({
          type: 'veltium/ws/consumptions',
          device_id: '<your_device_id>',
          aggr: 'month',
          records: 12
      }).then(data => {
          return data.map(item => [new Date(item[0]).getTime(), item[1]]);
      });
```

## WebSocket API Reference

The Veltium integration provides a custom WebSocket API to fetch historical energy data directly from Home Assistant's Long-Term Statistics (LTS).

### Fetch Consumption History
**Type:** `veltium/ws/consumptions`

**Parameters:**
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `device_id` | `string` | Yes | - | The unique ID of the Veltium charger. |
| `aggr` | `string` | No | `day` | Aggregation period: `hour`, `day`, `week`, `month`, or `year`. |
| `records` | `integer` | No | `30` | Number of periods to retrieve into the past. |

**Response Format:**
An array of tuples `[timestamp, value]`, where:
- `timestamp`: ISO-8601 formatted string (e.g., `"2025-03-12T00:00:00+01:00"`).
- `value`: Float representing energy consumed in kWh during that period.

#### Example Request
```json
{
  "id": 1,
  "type": "veltium/ws/consumptions",
  "device_id": "v12345",
  "aggr": "month",
  "records": 12
}
```
