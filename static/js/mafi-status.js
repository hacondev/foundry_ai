const boxLoaded = document.getElementById('boxLoaded');
const boxEmpty = document.getElementById('boxEmpty');
const switchEl = document.getElementById('mafiSwitch');

function updateState() {

  if (switchEl.checked) {
    // MAFI ZAŁADOWANA
    boxLoaded.style.display = "flex";
    boxEmpty.style.display = "none";

    boxLoaded.classList.add("blink");
    boxEmpty.classList.remove("blink");

  } else {
    // MAFI PUSTA
    boxEmpty.style.display = "flex";
    boxLoaded.style.display = "none";

    boxEmpty.classList.add("blink");
    boxLoaded.classList.remove("blink");
  }
}

// start
updateState();

switchEl.addEventListener("change", updateState);