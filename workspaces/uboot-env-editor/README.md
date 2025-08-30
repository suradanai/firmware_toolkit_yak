# uboot-env-editor

## Overview
`uboot-env-editor` is a Python application designed to facilitate the editing of U-Boot environment variables. It provides a user-friendly interface for parsing, modifying, and saving changes to the environment block, including the ability to adjust specific variables such as `bootdelay`.

## Features
- **Parse Environment Block**: Read and interpret the U-Boot environment data.
- **Edit Environment Variables**: Modify specific variables, including setting `bootdelay` to a desired value.
- **CRC Calculation**: Automatically calculate and validate the CRC of the environment block after modifications.
- **User Interface**: A simple and intuitive UI for interacting with the environment variables.

## Installation
To install the required dependencies, run:

```
pip install -r requirements.txt
```

## Usage
To start the application, run the following command:

```
python src/main.py
```

## Contributing
Contributions are welcome! Please feel free to submit a pull request or open an issue for any enhancements or bug fixes.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.