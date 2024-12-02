#!/usr/bin/env sh

# List of languages to keep
LANGUAGES_TO_KEEP="de fr it en en_GB en_AU"

# Find all locale directories inside .venv (case-insensitive)
LOCALE_DIRS=$(find .venv -type d -name "locale" -exec find {} -mindepth 1 -maxdepth 1 -type d \;)

# Loop through the found locale subdirectories and delete those not in the LANGUAGES_TO_KEEP list
for locale in $LOCALE_DIRS; do
    # Extract the last part of the path (the language code)
    lang=$(basename "$locale")

    # Check if the language is in the keep list
    found=0
    for keep in $LANGUAGES_TO_KEEP; do
        if [ "$lang" = "$keep" ]; then
            found=1
            break
        fi
    done

    # Delete or keep the directory
    if [ "$found" -eq 0 ]; then
        echo "Deleting $locale..."
        rm -rf "$locale"
    else
        echo "Keeping $locale"
    fi
done

echo "Locale cleanup complete."