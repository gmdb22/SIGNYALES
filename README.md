# SIGNYALES
An Edge AI-Powered Bimanual Smart Glove System for Filipino Sign Language Recognition via ESP-NOW at Blessed Ville Alfonso

fuck me 

# -------------------------------------------------

# I think you guys know the rules, never push to the main branch, before you start editing create your own branch to edit there blah blah blah blah blah 
# Also make sure u have python n git installed n shit sa vscode basta yon nakaano naman ata yung kelangan mainstall sa requirements.txt
# also brah iam just clauding the fuck outta this

# -------------------------------------------------

SETUP INSTRUCTIONS 
1. Clone the REPO 
git clone <repo url>

2. Create virtual environment 
pythong -m venv venv

3. Activate ts 
in the terminal 'venv\Scripts\activate'

4. Install dependencies 
pip install -r requirements.txt
# -------------------------------------------------

## Branching Convention

- `main` is always the working, stable version — nobody pushes directly to it.
- Each person works on a feature branch for their task, named like:
  - `feature/gesture-parser`
  - `feature/esp-now-pairing`
- When your feature works, open a Pull Request to merge it into `main`.
- Keep PRs small and focused — one task per branch/PR when possible.

# -------------------------------------------------

firmware/ # ESP32-S3 glove sensor code, ESP-NOW pairing, dongle firmware

pi-side/ # Raspberry Pi codebase: data sync, inference, TTS pipeline

data/ # Collected gesture datasets (raw + labeled CSVs)

models/ # Trained/quantized TinyML models
