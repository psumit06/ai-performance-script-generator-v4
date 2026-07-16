// Transaction Marker - Background Service Worker (MV3)
// Uses declarativeNetRequest to add headers dynamically.

const RULE_ID = 1;
const TX_HEADER = "x-transaction-name";
const TX_START_HEADER = "x-transaction-start";

let isActive = false;
let currentTransaction = "";

// Listen for messages from popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "START_TRANSACTION") {
    currentTransaction = message.name || "Unnamed";
    isActive = true;
    _addRule(currentTransaction).then(() => {
      sendResponse({ ok: true, transaction: currentTransaction });
    });
    return true;
  } else if (message.type === "STOP_TRANSACTION") {
    isActive = false;
    currentTransaction = "";
    _removeRule().then(() => {
      sendResponse({ ok: true });
    });
    return true;
  } else if (message.type === "GET_STATUS") {
    sendResponse({ active: isActive, transaction: currentTransaction });
  }
});

async function _addRule(txName) {
  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: [RULE_ID],
    addRules: [
      {
        id: RULE_ID,
        priority: 1,
        action: {
          type: "modifyHeaders",
          requestHeaders: [
            { header: TX_HEADER, operation: "set", value: txName },
            { header: TX_START_HEADER, operation: "set", value: "true" },
          ],
        },
        condition: {
          urlFilter: "*",
          resourceTypes: [
            "main_frame",
            "sub_frame",
            "stylesheet",
            "script",
            "image",
            "font",
            "object",
            "xmlhttprequest",
            "ping",
            "csp_report",
            "media",
            "websocket",
            "other",
          ],
        },
      },
    ],
  });
  console.log(`[TransactionMarker] Rule added: ${txName}`);
}

async function _removeRule() {
  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: [RULE_ID],
  });
  console.log("[TransactionMarker] Rule removed.");
}
