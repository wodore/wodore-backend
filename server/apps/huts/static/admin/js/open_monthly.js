function selectAllMonths(selectAll, name) {
  let radios = document.querySelectorAll(`input[name^="${name}_month_"]`);
  radios.forEach((radio) => {
    if (radio.value === selectAll.value) {
      radio.checked = true;
    }
  });
}
