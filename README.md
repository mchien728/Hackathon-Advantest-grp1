# Advantest AI Monitor Plugin

## Features
- **Accurate Anomaly Detection & Prediction** — Detects abnormal wafer test patterns and predicts sensor results in real time.
- **Anomaly Visualization** — Visualizes complex testing data through an intuitive monitoring dashboard.
- **Proactive Alert Notifications** — Automatically sends Gmail alerts when anomalies are detected.

## Environment Access
1. Login https://sandbox.gemini.te-cloud.advantest.com/dashboard/virtual-machine
2. Start both VMs and connect them, and you will access the HC.
3. To connect the Edge Server, go to http://advantestcell.local:29080 or `ssh edge`

## How to Deploy
### Frontend
1. Copy `apps/` into your server.
2. Start a Python environment manager (e.g. venv, conda, ...).
3. `pip install -r requirements.txt`
4. Export `OPENROUTER_API_KEY` into your ChatGPT API key.
5. `python dashboard.py`

### HC
1. Copy `SmarTest` into the HC VM.
2. Create SSH tunnel from the Frontend server to here.
```sh
ssh edge -L 5000:localhost:5000
```
3. `./runTp.sh load`
4. `./runTp.sh eng_run 20`

### Edge
1. Copy `Edge/oneAPI_py3.10` into Edge (ssh edge in VM).
2. Create SSH tunnel from HC to here.
```sh
ssh [HC's internel IP] -L 5000:localhost:5000
```
3. Export the Frontend server's url into `ACS_LOG_LEVEL`. (localhost if you build the ssh tunnel)
```sh
export $ACS_LOG_LEVEL=http://127.0.0.1:5000/api/state
```
4. Run this command.
```sh
eval "$(grep '^export ONEAPI_' ~/.bashrc)"
PROBE_OUT=$(pwd)/probe.json python3 tools/machine_probe.py 2>&1 | tee $(pwd)/probe.log
```

## Update Notes
- 2026.09.14: Upload `Case_Event` directory.
- 2026.09.20: Finish the full project.