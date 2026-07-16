// Transaction Marker - Popup Script

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const txNameInput = document.getElementById("txName");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const txList = document.getElementById("txList");
const clearBtn = document.getElementById("clearBtn");

// Load state on open
chrome.runtime.sendMessage({ type: "GET_STATUS" }, (res) => {
  updateUI(res.active, res.transaction);
});

// Load recorded transactions from storage
chrome.storage.local.get(["transactions"], (data) => {
  renderTxList(data.transactions || []);
});

startBtn.addEventListener("click", () => {
  const name = txNameInput.value.trim();
  if (!name) {
    txNameInput.style.borderColor = "#ff3366";
    txNameInput.focus();
    return;
  }
  startBtn.disabled = true;
  startBtn.textContent = "Starting...";
  chrome.runtime.sendMessage({ type: "START_TRANSACTION", name }, (res) => {
    startBtn.disabled = false;
    startBtn.textContent = "Start Transaction";
    if (res && res.ok) {
      updateUI(true, name);
      chrome.storage.local.get(["transactions"], (data) => {
        const list = data.transactions || [];
        list.push({ name, timestamp: new Date().toISOString() });
        chrome.storage.local.set({ transactions: list });
        renderTxList(list);
      });
    }
  });
});

stopBtn.addEventListener("click", () => {
  stopBtn.disabled = true;
  stopBtn.textContent = "Stopping...";
  chrome.runtime.sendMessage({ type: "STOP_TRANSACTION" }, (res) => {
    stopBtn.disabled = false;
    stopBtn.textContent = "Stop Transaction";
    if (res && res.ok) {
      updateUI(false, "");
      txNameInput.value = "";
    }
  });
});

txNameInput.addEventListener("focus", () => {
  txNameInput.style.borderColor = "";
});

clearBtn.addEventListener("click", () => {
  chrome.storage.local.set({ transactions: [] });
  renderTxList([]);
});

function updateUI(active, txName) {
  if (active) {
    statusDot.classList.add("active");
    statusText.textContent = `Recording: ${txName}`;
    startBtn.style.display = "none";
    stopBtn.style.display = "block";
    txNameInput.value = txName;
    txNameInput.disabled = true;
  } else {
    statusDot.classList.remove("active");
    statusText.textContent = "Inactive";
    startBtn.style.display = "block";
    stopBtn.style.display = "none";
    txNameInput.disabled = false;
  }
}

function renderTxList(transactions) {
  if (!transactions.length) {
    txList.innerHTML = '<div style="color:#666;">No transactions recorded</div>';
    return;
  }
  txList.innerHTML = transactions
    .map(
      (tx, i) =>
        `<div class="tx-item"><span class="tx-name">${i + 1}. ${tx.name}</span><span>${new Date(tx.timestamp).toLocaleTimeString()}</span></div>`
    )
    .join("");
}
