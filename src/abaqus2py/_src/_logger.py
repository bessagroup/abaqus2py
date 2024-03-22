import logging

logger = logging.getLogger('abaqus2py')

# Create a handler for logging to the console
console_handler = logging.StreamHandler()
# Set the logging level for the handler
console_handler.setLevel(logging.DEBUG)

# Create a formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)  # Attach the formatter to the handler

# Add the handler to the logger
logger.addHandler(console_handler)
