# Simple Python App — Calculator Test Target

![Python](https://img.shields.io/badge/Python-Learning%20utility-3776AB?logo=python&logoColor=white)
![Purpose](https://img.shields.io/badge/Purpose-Test%20subject-lightgrey)

A small Python calculator module useful for **basic unit-testing demonstrations** and exploratory automated test generation. It is a **supporting test subject**, not a primary thesis implementation or the final FastAPI system under test.

## Implemented operations

| Function | Behavior |
|---|---|
| `add(a, b)` | Adds two numbers |
| `subtract(a, b)` | Subtracts second operand from first |
| `divide(a, b)` | Divides operands; raises `ValueError` for division by zero |

All logic is located in [`app/calculator.py`](app/calculator.py). The checked repository does not contain an included pytest suite or CI configuration.

## Try it locally

```bash
git clone https://github.com/ChiththajaGalabodage/Simple-Pythone-App.git
cd Simple-Pythone-App
python -c "from app.calculator import add, subtract, divide; print(add(2, 3)); print(subtract(5, 2)); print(divide(10, 2))"
```

## Example unit tests (optional, not yet committed in this repo)

```python
import pytest
from app.calculator import add, subtract, divide

def test_add():
    assert add(2, 3) == 5

def test_subtract():
    assert subtract(5, 2) == 3

def test_zero_division():
    with pytest.raises(ValueError):
        divide(5, 0)
```

Save these tests as `test_calculator.py` and run `python -m pytest -q` after installing pytest if you want to extend the sample. These are illustrative examples, **not a reported experiment**.

## Relation to research

Simple, deterministic modules are useful for validating that test-generation tooling can discover functions, generate valid tests, and detect obvious logic changes. Such smoke tests cannot support claims about end-to-end CI/CD performance on the final LLM-CTF case-study service.

**Author:** [Chiththaja Galabodage](https://github.com/ChiththajaGalabodage)
