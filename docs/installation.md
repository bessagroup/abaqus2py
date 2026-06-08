# Installation

- Purpose: quick ways to install `abaqus2py` for users and contributors.
- Requirements: Python `>=3.11`.

### Quick Install (pip)

- Recommended for most users.

```bash
pip install abaqus2py
```

### From Source

- Use this for local development or to contribute.
```bash
git clone https://github.com/bessagroup/abaqus2py
cd abaqus2py

# Editable install with extras you need
pip install -e ".[tests,docs,dev]"
```