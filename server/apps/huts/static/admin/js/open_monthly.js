function selectAllMonths(selectAll, widgetName) {
  const value = selectAll.value;
  const radios = document.querySelectorAll(`input[name^="${widgetName}_"]`);
  const selectAllRadio = document.querySelector(
    `input[name="${widgetName}_select_all"]:checked`,
  );

  // If the same value is selected again, restore previous values
  if (selectAllRadio && selectAllRadio.dataset.previousValue === value) {
    // Restore previous values
    radios.forEach((radio) => {
      if (radio.name !== `${widgetName}_select_all`) {
        const previousValue = radio.dataset.previousValue;
        if (previousValue) {
          radio.checked = radio.value === previousValue;
        } else {
          radio.checked = false;
        }
      }
    });
    selectAll.checked = false;
    selectAllRadio.dataset.previousValue = undefined;
  } else {
    selectAllRadio.dataset.previousValue = value;
    // Store current values before changing
    radios.forEach((radio) => {
      if (radio.name !== `${widgetName}_select_all` && radio.checked) {
        radio.dataset.previousValue = radio.value;
      }
    });

    // Select all with the new value
    radios.forEach((radio) => {
      if (radio.value === selectAll.value) {
        radio.checked = true;
      }
    });
  }
}

function uncheckSelectAll(widgetName) {
  const selectAllRadio = document.querySelector(
    `input[name="${widgetName}_select_all"]:checked`,
  );
  if (selectAllRadio) {
    selectAllRadio.checked = false;
    selectAllRadio.dataset.previousValue = undefined;
  }
}

function resetMonthlyWidget(widgetName) {
  const radios = document.querySelectorAll(`input[name^="${widgetName}_"]`);
  const selectAllRadio = document.querySelector(
    `input[name="${widgetName}_select_all"]`,
  );

  // Reset all month radio buttons to their initial values
  radios.forEach((radio) => {
    if (radio.name !== `${widgetName}_select_all`) {
      const initialValue = radio.dataset.initialValue;
      radio.checked = radio.value === initialValue;
      radio.dataset.previousValue = undefined;
    }
  });

  // Uncheck select all radio
  if (selectAllRadio) {
    selectAllRadio.checked = false;
    selectAllRadio.dataset.previousValue = undefined;
  }
}
