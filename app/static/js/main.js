function escapeHTML(value) {
    return String(value ?? "-")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function appUrl(path) {
    const rootPath = document.body?.dataset.rootPath || "";
    return `${rootPath}${path}`;
}

function escapeCSS(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(value);
    }

    return String(value).replace(/["\\]/g, "\\$&");
}

function openDetail(ordCode) {
    const panel = document.getElementById("side-panel");
    const backdrop = document.getElementById("panel-backdrop");
    const content = document.getElementById("detail-content");

    if (!panel || !content) {
        return;
    }

    content.innerHTML = '<div class="panel-loading">불러오는 중...</div>';
    panel.classList.add("open");
    if (backdrop) {
        backdrop.classList.add("open");
    }

    fetch(appUrl(`/api/order/${encodeURIComponent(ordCode)}`))
        .then((res) => {
            if (!res.ok) {
                throw new Error("detail fetch failed");
            }
            return res.json();
        })
        .then((data) => {
            renderDetail(data);
        })
        .catch(() => {
            content.innerHTML = '<div class="empty">표시할 데이터가 없습니다.</div>';
        });
}

function renderDetail(data) {
    const content = document.getElementById("detail-content");
    const items = data.items || [];

    if (!content) {
        return;
    }

    if (!items.length) {
        content.innerHTML = '<div class="empty">표시할 데이터가 없습니다.</div>';
        return;
    }

    const first = items[0];
    const trackingNumber = first.logis_out_no || "";
    const reservationDate = first.reservation_date || "";
    const canComplete = ["판매접수", "발주요청"].includes(first.ord_dlv_status);
    const canEditTracking = canComplete || first.ord_dlv_status === "출고완료";
    const trackingAction = canComplete ? "complete" : "update";
    const trackingLabel = canComplete ? "운송장번호 입력" : "운송장번호 수정";
    const trackingButton = canComplete ? "완료 처리" : "수정 저장";
    const noticeHTML = data.notice ? `<div class="detail-notice">${escapeHTML(data.notice)}</div>` : "";
    const trackingFormHTML = canEditTracking ? `
        <form class="detail-tracking-form" data-order-code="${escapeHTML(data.ord_code || first.ord_code)}" data-action="${trackingAction}" onsubmit="saveTrackingNumber(event)">
            <label for="tracking-number">${trackingLabel}</label>
            <div class="detail-tracking-row">
                <input id="tracking-number" name="tracking_number" type="text" maxlength="30" value="${escapeHTML(trackingNumber)}" autocomplete="off" required>
                <button type="submit">${trackingButton}</button>
            </div>
            <div class="detail-message" aria-live="polite"></div>
        </form>
    ` : "";
    const reservationFormHTML = `
        <form class="reservation-form detail-reservation-form" data-order-code="${escapeHTML(data.ord_code || first.ord_code)}" onsubmit="saveReservationDate(event)">
            <label for="reservation-date">예약일</label>
            <div class="reservation-row">
                <input id="reservation-date" type="date" name="reservation_date" value="${escapeHTML(reservationDate)}" aria-label="예약일">
                <button type="submit">저장</button>
            </div>
            <div class="reservation-display" data-order-code="${escapeHTML(data.ord_code || first.ord_code)}">
                ${reservationDate ? `<span class="reservation-date">예약 (${escapeHTML(reservationDate)})</span>` : "<span>-</span>"}
            </div>
        </form>
    `;
    const itemHTML = items.map((item) => {
        const rowClass = item.row_class || "";
        const statusClass = item.status_class || "status-progress";

        return `
            <div class="detail-item ${rowClass}">
                <div class="detail-item-title">${escapeHTML(item.gd_name)}</div>
                <div class="${statusClass}">${escapeHTML(item.ord_dlv_status)}</div>
            </div>
        `;
    }).join("");

    content.innerHTML = `
        <div class="detail-summary">
            ${noticeHTML}
            <div class="detail-label">주문번호</div>
            <div class="detail-code">${escapeHTML(data.ord_code || first.ord_code)}</div>
            <div class="detail-grid">
                <div>
                    <span>주문자</span>
                    <strong>${escapeHTML(first.CUSTOMER)}</strong>
                </div>
                <div>
                    <span>주문자 연락처</span>
                    <strong>${escapeHTML(first.CUSTOMER_MOBILE)}</strong>
                </div>
                <div>
                    <span>수령자</span>
                    <strong>${escapeHTML(first.dlv_name)}</strong>
                </div>
                <div>
                    <span>수령자 연락처</span>
                    <strong>${escapeHTML(first.dlv_tel_1)}</strong>
                </div>
                <div>
                    <span>운송장번호</span>
                    <strong>${escapeHTML(trackingNumber)}</strong>
                </div>
            </div>
            ${reservationFormHTML}
            ${trackingFormHTML}
            <div class="detail-address">
                <span>주소</span>
                <strong>${escapeHTML(first.dlv_addr_1)}</strong>
            </div>
        </div>
        <div class="detail-list">
            ${itemHTML}
        </div>
    `;
}

function saveTrackingNumber(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const input = form.querySelector('input[name="tracking_number"]');
    const button = form.querySelector('button[type="submit"]');
    const message = form.querySelector(".detail-message");
    const ordCode = form.dataset.orderCode;
    const action = form.dataset.action || "complete";
    const trackingNumber = input ? input.value.trim() : "";
    const defaultButtonText = action === "complete" ? "완료 처리" : "수정 저장";

    if (!ordCode || !trackingNumber) {
        if (message) {
            message.textContent = "운송장번호를 입력해주세요.";
        }
        return;
    }

    const confirmMessage = action === "complete"
        ? `운송장번호 ${trackingNumber}로 저장하고 출고완료 처리할까요?`
        : `운송장번호를 ${trackingNumber}로 수정할까요?`;

    if (!window.confirm(confirmMessage)) {
        return;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "저장 중...";
    }
    if (message) {
        message.textContent = "";
    }

    fetch(appUrl(`/api/order/${encodeURIComponent(ordCode)}/tracking`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ tracking_number: trackingNumber }),
    })
        .then((res) => {
            if (!res.ok) {
                return res.json().then((data) => {
                    throw new Error(data.detail || "운송장번호 저장에 실패했습니다.");
                });
            }
            return res.json();
        })
        .then((data) => {
            if (data.action === "completed") {
                removeOrderRows(ordCode);
                data.notice = "운송장번호 저장과 출고완료 처리가 완료되었습니다.";
            } else {
                data.notice = "운송장번호가 수정되었습니다.";
            }
            renderDetail(data);
        })
        .catch((error) => {
            if (message) {
                message.textContent = error.message;
            }
            if (button) {
                button.disabled = false;
                button.textContent = defaultButtonText;
            }
        });
}

function removeOrderRows(ordCode) {
    document.querySelectorAll(`.order-row[data-order-code="${escapeCSS(ordCode)}"]`).forEach((row) => {
        const tbody = row.closest("tbody");
        const colspan = row.children.length || 1;

        row.remove();

        if (tbody && !tbody.querySelector(".order-row")) {
            const emptyRow = document.createElement("tr");
            emptyRow.innerHTML = `<td colspan="${colspan}" class="empty">표시할 데이터가 없습니다.</td>`;
            tbody.appendChild(emptyRow);
        }
    });
}

function removeSaleRow(saleId) {
    const row = document.querySelector(`.order-row[data-sale-id="${escapeCSS(saleId)}"]`);

    if (!row) {
        return;
    }

    const tbody = row.closest("tbody");
    const colspan = row.children.length || 1;

    row.remove();

    if (tbody && !tbody.querySelector(".order-row")) {
        const emptyRow = document.createElement("tr");
        emptyRow.innerHTML = `<td colspan="${colspan}" class="empty">표시할 데이터가 없습니다.</td>`;
        tbody.appendChild(emptyRow);
    }
}

function markSaleRowSaved(saleId, trackingNumber) {
    const row = document.querySelector(`.order-row[data-sale-id="${escapeCSS(saleId)}"]`);

    if (!row) {
        return;
    }

    const form = row.querySelector(".inline-tracking-form");
    const input = form ? form.querySelector('input[name="tracking_number"]') : null;
    const button = form ? form.querySelector('button[type="submit"]') : null;
    const message = form ? form.querySelector(".inline-message") : null;

    if (input) {
        input.value = trackingNumber;
        input.disabled = true;
    }
    if (button) {
        button.disabled = true;
        button.textContent = "완료";
    }
    if (message) {
        message.textContent = "저장완료";
        message.classList.add("is-success");
    }
}

function saveInlineTrackingNumber(event) {
    event.preventDefault();
    event.stopPropagation();

    const form = event.currentTarget;
    const input = form.querySelector('input[name="tracking_number"]');
    const button = form.querySelector('button[type="submit"]');
    const message = form.querySelector(".inline-message");
    const ordCode = form.dataset.orderCode;
    const saleId = form.dataset.saleId;
    const trackingNumber = input ? input.value.trim() : "";

    if (!ordCode || !saleId) {
        if (message) {
            message.textContent = "상품번호 없음";
        }
        return;
    }

    if (!trackingNumber) {
        if (message) {
            message.textContent = "운송장번호를 입력해주세요.";
        }
        return;
    }

    if (!window.confirm(`운송장번호 ${trackingNumber} 입력 완료할까요?`)) {
        return;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "저장 중";
    }
    if (message) {
        message.textContent = "";
    }

    fetch(appUrl(`/api/order/${encodeURIComponent(ordCode)}/item/${encodeURIComponent(saleId)}/tracking`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ tracking_number: trackingNumber }),
    })
        .then((res) => {
            if (!res.ok) {
                return res.json().then((data) => {
                    throw new Error(data.detail || "운송장번호 저장에 실패했습니다.");
                });
            }
            return res.json();
        })
        .then((data) => {
            markSaleRowSaved(data.sale_id || saleId, data.tracking_number || trackingNumber);
        })
        .catch((error) => {
            if (message) {
                message.textContent = error.message;
            }
            if (button) {
                button.disabled = false;
                button.textContent = "저장";
            }
        });
}

function renderReservationDisplay(form, reservationDate, message) {
    const display = form.querySelector(".reservation-display");

    if (!display) {
        return;
    }

    const dateHTML = reservationDate
        ? `<span class="reservation-date">예약 (${escapeHTML(reservationDate)})</span>`
        : "<span>-</span>";
    const messageHTML = message
        ? `<span class="reservation-message">${escapeHTML(message)}</span>`
        : "";

    display.innerHTML = `${dateHTML}${messageHTML}`;
}

function updateReservationDisplays(ordCode, reservationDate) {
    if (!ordCode) {
        return;
    }

    const dateHTML = reservationDate
        ? `<span class="reservation-date">예약 (${escapeHTML(reservationDate)})</span>`
        : "<span>-</span>";

    document.querySelectorAll(`.reservation-display[data-order-code="${escapeCSS(ordCode)}"]`).forEach((display) => {
        display.innerHTML = dateHTML;
    });
}

function saveReservationDate(event) {
    event.preventDefault();
    event.stopPropagation();

    const form = event.currentTarget;
    const input = form.querySelector('input[name="reservation_date"]');
    const button = form.querySelector('button[type="submit"]');
    const ordCode = form.dataset.orderCode;
    const reservationDate = input ? input.value.trim() : "";

    if (!ordCode) {
        renderReservationDisplay(form, reservationDate, "주문번호 없음");
        return;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "저장 중";
    }

    fetch(appUrl(`/api/order/${encodeURIComponent(ordCode)}/reservation`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ reservation_date: reservationDate }),
    })
        .then((res) => {
            if (!res.ok) {
                return res.json().then((data) => {
                    throw new Error(data.detail || "예약일 저장에 실패했습니다.");
                });
            }
            return res.json();
        })
        .then((data) => {
            updateReservationDisplays(ordCode, data.reservation_date);
            renderReservationDisplay(form, data.reservation_date, "저장됨");
        })
        .catch((error) => {
            renderReservationDisplay(form, reservationDate, error.message);
        })
        .finally(() => {
            if (button) {
                button.disabled = false;
                button.textContent = "저장";
            }
        });
}

function closePanel() {
    const panel = document.getElementById("side-panel");
    const backdrop = document.getElementById("panel-backdrop");

    if (panel) {
        panel.classList.remove("open");
    }

    if (backdrop) {
        backdrop.classList.remove("open");
    }
}

function refreshCache(cacheKey) {
    fetch(appUrl(`/refresh-cache/${encodeURIComponent(cacheKey)}`))
        .then((res) => res.json())
        .then((data) => {
            if (data.ok) {
                window.location.reload();
            }
        });
}

function switchMainProgressTab(tabName) {
    document.querySelectorAll("[data-main-progress-tab]").forEach((button) => {
        button.classList.toggle("active", button.dataset.mainProgressTab === tabName);
    });

    document.querySelectorAll("[data-main-progress-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.mainProgressPanel !== tabName;
    });
}

window.openDetail = openDetail;
window.closePanel = closePanel;
window.refreshCache = refreshCache;
window.saveTrackingNumber = saveTrackingNumber;
window.saveInlineTrackingNumber = saveInlineTrackingNumber;
window.saveReservationDate = saveReservationDate;

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".inline-tracking-form").forEach((form) => {
        form.addEventListener("click", (event) => {
            event.stopPropagation();
        });
        form.addEventListener("submit", saveInlineTrackingNumber);
    });

    document.querySelectorAll(".reservation-form").forEach((form) => {
        form.addEventListener("click", (event) => {
            event.stopPropagation();
        });
        form.addEventListener("submit", saveReservationDate);
    });

    document.querySelectorAll(".detail-button").forEach((button) => {
        button.addEventListener("click", (event) => {
            const ordCode = button.dataset.orderCode;

            event.stopPropagation();
            if (ordCode) {
                openDetail(ordCode);
            }
        });
    });

    document.querySelectorAll(".order-row").forEach((row) => {
        row.addEventListener("click", (event) => {
            if (event.target.closest(".inline-tracking-form")) {
                return;
            }

            const ordCode = row.dataset.orderCode;

            if (ordCode) {
                openDetail(ordCode);
            }
        });
    });

    document.querySelectorAll(".refresh-button").forEach((button) => {
        button.addEventListener("click", () => {
            const cacheKey = button.dataset.cacheKey;

            if (cacheKey) {
                button.disabled = true;
                button.textContent = "새로고침 중...";
                refreshCache(cacheKey);
            }
        });
    });

    document.querySelectorAll("[data-main-progress-tab]").forEach((button) => {
        button.addEventListener("click", () => {
            switchMainProgressTab(button.dataset.mainProgressTab);
        });
    });
});

document.addEventListener("click", (event) => {
    if (event.target.closest(".inline-tracking-form")) {
        event.stopPropagation();
    }
}, true);

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        closePanel();
    }
});
