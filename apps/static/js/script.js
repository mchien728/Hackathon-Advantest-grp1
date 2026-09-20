let hoveredTD = null;
let selectedTD = null;
let hoveredSite = null;
let selectedSite = null;
let selectedWafer = null;
let latestLiveState = null;

const waferLayout = [
    [3,0], [4,0], [5,0], [6,0], [7,0], [8,0],

    [2,1], [3,1], [4,1], [5,1],
    [6,1], [7,1], [8,1], [9,1],

    [1,2], [2,2], [3,2], [4,2], [5,2],
    [6,2], [7,2], [8,2], [9,2], [10,2],

    [0,3], [1,3], [2,3], [3,3], [4,3], [5,3],
    [6,3], [7,3], [8,3], [9,3], [10,3], [11,3],

    [0,4], [1,4], [2,4], [3,4], [4,4], [5,4],
    [6,4], [7,4], [8,4], [9,4], [10,4], [11,4],

    [1,5], [2,5], [3,5], [4,5], [5,5],
    [6,5], [7,5], [8,5], [9,5], [10,5],

    [1,6], [2,6], [3,6], [4,6], [5,6],
    [6,6], [7,6], [8,6], [9,6], [10,6],

    [2,7], [3,7], [4,7], [5,7],
    [6,7], [7,7], [8,7], [9,7],

    [4,8], [5,8], [6,8], [7,8]
];

function updateWaferHighlight() {

    const activeTD =
        selectedTD !== null
            ? selectedTD
            : hoveredTD;

    const activeSite =
        selectedSite !== null
            ? selectedSite
            : hoveredSite;

    const dies =
        document.querySelectorAll('.wafer-die');

    dies.forEach(die => {

        const dieTD =
            die.dataset.td === ''
                ? null
                : Number(die.dataset.td);

        const dieSite =
            die.dataset.site === ''
                ? null
                : Number(die.dataset.site);

        // 沒有選 TD，也沒有選 Site
        if (
            activeTD === null &&
            activeSite === null
        ) {
            die.classList.remove('highlight');
            die.classList.remove('dimmed');
            return;
        }

        // 有 TD 條件時，要符合 TD
        const matchesTD =
            activeTD === null ||
            dieTD === activeTD;

        // 有 Site 條件時，要符合 Site
        const matchesSite =
            activeSite === null ||
            dieSite === activeSite;

        if (matchesTD && matchesSite) {
            die.classList.add('highlight');
            die.classList.remove('dimmed');
        } else {
            die.classList.remove('highlight');
            die.classList.add('dimmed');
        }
    });
}


function updateTimelineSelection() {

    document
        .querySelectorAll('.timeline-dot')
        .forEach(dot => {

            const td =
                Number(dot.dataset.td);

            dot.classList.toggle(
                'selected',
                selectedTD === td
            );
        });
}

function renderTimeline(waferMap, currentTD, indicators) {
    const track = document.getElementById('timeline-track');
    const currentLabel = document.getElementById('timeline-current');

    if (!waferMap || !waferMap.rows) {
        track.innerHTML = '<div class="timeline-empty">Waiting for test progress...</div>';
        currentLabel.textContent = '-';
        return;
    }

    currentLabel.textContent = currentTD != null ? `Current: TD ${currentTD}` : '-';
    track.innerHTML = '';

    for (let td = 1; td <= 20; td++) {
        const item = document.createElement('div');
        item.className = 'timeline-item';

        const dot = document.createElement('div');
        dot.className = 'timeline-dot';

        const tdRows = waferMap.rows.filter(row => row[0] === td);

        if (tdRows.length > 0) {
            const hasFailed = tdRows.some(row => row[5] === false);
            const hasSuspect = tdRows.some(row => row[6] === true);

            if (hasFailed) dot.classList.add('status-failed');
            else if (hasSuspect) dot.classList.add('status-suspect');
            else dot.classList.add('status-passed');
        }
        if (tdRows.length > 0) {
            const hasFailed = tdRows.some(row => row[5] === false);
            const hasSuspect = tdRows.some(row => row[6] === true);

            let tooltip = `TD ${td}`;

            if (hasFailed) tooltip += '\nStatus: Failed';
            else if (hasSuspect) tooltip += '\nStatus: Suspect';
            else tooltip += '\nStatus: Passed';

            if (hasFailed || hasSuspect) {
                const tdReasons = (indicators || []).filter(indicator =>
                    indicator.triggered &&
                    indicator.detail?.onset_td != null &&
                    td >= indicator.detail.onset_td
                );

                if (tdReasons.length > 0) {
                    tooltip += '\nPossible cause: ' + tdReasons.map(item => item.name).join(', ');
                }
            }

            dot.title = tooltip;
        }
        dot.dataset.td = td;
        dot.textContent = td;

        if (currentTD != null && td > currentTD) {
            dot.classList.add('future');
        }

        dot.addEventListener('mouseenter', () => {
            if (selectedTD !== null || td > currentTD) return;

            hoveredTD = td;
            updateWaferHighlight();
        });

        dot.addEventListener('mouseleave', () => {
            if (selectedTD !== null || td > currentTD) return;

            hoveredTD = null;
            updateWaferHighlight();
        });

        dot.addEventListener('click', () => {
            if (td > currentTD) return;

            hoveredTD = null;
            selectedTD = selectedTD === td ? null : td;

            updateTimelineSelection();
            updateWaferHighlight();
        });

        item.appendChild(dot);

        if (td < 20) {
            const line = document.createElement('div');
            line.className = 'timeline-line';

            if (currentTD != null && td >= currentTD) {
                line.classList.add('future');
            }

            item.appendChild(line);
        }

        track.appendChild(item);
    }

    updateTimelineSelection();
}

function updateSiteSelection() {

    document
        .querySelectorAll('.site-item')
        .forEach(item => {

            const site =
                Number(item.dataset.site);

            item.classList.toggle(
                'selected',
                selectedSite === site
            );
        });
}

function renderWaferMap(waferMap) {

    const container =
        document.getElementById('wafer-map');

    if (
        !waferMap ||
        !waferMap.rows ||
        waferMap.rows.length === 0
    ) {
        container.innerHTML =
            '<div class="empty-state">Waiting for wafer data...</div>';
        return;
    }


    const columns = waferMap.columns || [];

    const tdIndex = columns.indexOf('td');
    const siteIndex = columns.indexOf('site');
    const xIndex = columns.indexOf('x');
    const yIndex = columns.indexOf('y');
    const sbinIndex = columns.indexOf('sbin');
    const passedIndex = columns.indexOf('passed');
    const suspectIndex = columns.indexOf('suspect');


    const testedDies = new Map();

    waferMap.rows.forEach(row => {

        const x = row[xIndex];
        const y = row[yIndex];

        testedDies.set(`${x},${y}`, {
            td: row[tdIndex],
            site: row[siteIndex],
            x: x,
            y: y,
            sbin: row[sbinIndex],
            passed: row[passedIndex],
            suspect: row[suspectIndex]
        });
    });


    const allDies = waferLayout.map(([x, y]) => {

        const tested =
            testedDies.get(`${x},${y}`);

        // Not tested yet
        if (!tested) {
            return {
                td: null,
                site: null,
                x: x,
                y: y,
                sbin: null,
                passed: null,
                suspect: false,
                tested: false,
                color: '#e1e5eb'
            };
        }


        let color = '#22c55e';

        if (!tested.passed) {
            color = '#ef4444';
        } else if (tested.suspect) {
            color = '#f59e0b';
        }

        return {
            ...tested,
            tested: true,
            color: color
        };
    });


    const extent = waferMap.extent;

    let minX;
    let maxX;
    let minY;
    let maxY;

    if (extent) {
        minX = extent.x[0];
        maxX = extent.x[1];
        minY = extent.y[0];
        maxY = extent.y[1];
    } else {
        const xs = allDies.map(die => die.x);
        const ys = allDies.map(die => die.y);

        minX = Math.min(...xs);
        maxX = Math.max(...xs);
        minY = Math.min(...ys);
        maxY = Math.max(...ys);
    }


    const cellSize = 40;
    const gap = 5;
    const padding = 20;

    const width =
        (maxX - minX + 1) * (cellSize + gap) + padding * 2;

    const height =
        (maxY - minY + 1) * (cellSize + gap) + padding * 2;


    let svg =
        `<svg viewBox="0 0 ${width} ${height}"
            xmlns="http://www.w3.org/2000/svg">`;


    allDies.forEach(die => {

        const x =
            padding + (die.x - minX) * (cellSize + gap);

        const y =
            padding + (die.y - minY) * (cellSize + gap);

        let status;

        if (!die.tested) {
            status = 'Not tested';
        } else if (!die.passed) {
            status = 'Fail';
        } else if (die.suspect) {
            status = 'Suspect';
        } else {
            status = 'Pass';
        }

        let tooltip;

        if (!die.tested) {

            tooltip =
                `(${die.x}, ${die.y}) | Not tested`;

        } else {

            tooltip =
                `TD ${die.td ?? '-'} | ` +
                `Site ${die.site ?? '-'} | ` +
                `(${die.x}, ${die.y}) | ` +
                `Bin ${die.sbin ?? '-'} | ` +
                `${status}`;
        }

        svg += `
            <rect
                class="wafer-die"
                data-td="${die.td ?? ''}"
                data-site="${die.site ?? ''}"
                x="${x}"
                y="${y}"
                width="${cellSize}"
                height="${cellSize}"
                rx="5"
                fill="${die.color}">
                <title>${tooltip}</title>
            </rect>
        `;
    });


    svg += '</svg>';
    container.innerHTML = svg;
    updateWaferHighlight();
}

function renderSiteOverview(waferMap) {
    const rows = waferMap?.rows || [];
    const columns = waferMap?.columns || [];

    const siteIndex = columns.indexOf('site');
    const passedIndex = columns.indexOf('passed');
    const suspectIndex = columns.indexOf('suspect');

    if (siteIndex === -1 || passedIndex === -1 || suspectIndex === -1) return;

    for (let site = 1; site <= 4; site++) {
        const card = document.getElementById('site-' + site);
        if (!card) continue;

        const siteItem = document.querySelector(`.site-item[data-site="${site}"]`);
        const siteRows = rows.filter(row => row[siteIndex] === site);
        const failedCount = siteRows.filter(row => !row[passedIndex]).length;
        const suspectCount = siteRows.filter(row => row[suspectIndex]).length;
        
        if (siteItem) {
            siteItem.classList.remove('status-passed', 'status-suspect', 'status-failed');

            if (failedCount > 0) {
                siteItem.classList.add('status-failed');
            } else if (suspectCount > 0) {
                siteItem.classList.add('status-suspect');
            } else if (siteRows.length > 0) {
                siteItem.classList.add('status-passed');
            }

            let siteTooltip = `Site ${site}`;

            if (failedCount > 0) {
                siteTooltip += `\nStatus: Failed (${failedCount})`;
            } else if (suspectCount > 0) {
                siteTooltip += `\nStatus: Suspect (${suspectCount})`;
            } else if (siteRows.length > 0) {
                siteTooltip += '\nStatus: Passed';
            } else {
                siteTooltip += '\nStatus: Not Tested';
            }

            siteItem.title = siteTooltip;
        }
        let tooltip = `Site ${site}`;

        if (failedCount > 0) tooltip += `\nStatus: Failed (${failedCount})`;
        else if (suspectCount > 0) tooltip += `\nStatus: Suspect (${suspectCount})`;
        else if (siteRows.length > 0) tooltip += '\nStatus: Passed';
        else tooltip += '\nStatus: Not Tested';

        card.title = tooltip;

        const status = card.querySelector('.site-status');

        card.classList.remove('alert');

        if (failedCount > 0) {
            card.classList.add('alert');
            card.style.backgroundColor = '#fee2e2';
            card.style.borderColor = '#fca5a5';
            status.textContent = `${failedCount} Failed`;
        } else if (suspectCount > 0) {
            card.classList.add('alert');
            card.style.backgroundColor = '#fef3c7';
            card.style.borderColor = '#fcd34d';
            status.textContent = `${suspectCount} Suspect`;
        } else if (siteRows.length > 0) {
            card.style.backgroundColor = '#dcfce7';
            card.style.borderColor = '#86efac';
            status.textContent = 'Normal';
        } else {
            card.style.backgroundColor = '';
            card.style.borderColor = '';
            status.textContent = 'Not Tested';
        }
    }

    updateSiteSelection();
}

function renderWaferOverview(state) {
    const list = document.getElementById('wafer-overview-list');
    if (!list) return;

    list.innerHTML = '';

    const wafers = state?.wafers || [];

    if (wafers.length === 0) {
        list.innerHTML =
            '<div class="wafer-overview-empty">No wafer data available.</div>';
        return;
    }

    wafers.forEach(wafer => {
        const row = document.createElement('div');
        row.className = 'wafer-overview-row clickable';

        const displayLabel =
            wafer.headline ??
            wafer.label ??
            'Normal';

        const isNormal =
            displayLabel === 'Normal';

        const yieldCriterion =
            wafer.criteria?.find(item => item.key === 'yield');

        const isLowYield =
            yieldCriterion?.triggered === true;

        const yieldValue =
            wafer.yield != null
                ? `${(wafer.yield * 100).toFixed(1)}%`
                : '-';

        const onset =
            wafer.onset_td != null
                ? `TD ${wafer.onset_td}`
                : '-';

        const statusClass = wafer.current
            ? 'testing'
            : isNormal
                ? 'normal'
                : 'anomaly';

        const statusText = wafer.current
            ? 'Testing'
            : isNormal
                ? 'Normal'
                : 'Anomaly';

        row.addEventListener('click', () => {
            openWaferDetail(wafer);
        });

        row.innerHTML = `
            <div class="wafer-overview-name">${wafer.wafer}</div>

            <div>
                <span class="wafer-status ${statusClass}">
                    ${statusText}
                </span>
            </div>

            <div class="wafer-detection ${!isNormal ? 'anomaly' : ''}">
                ${displayLabel}
            </div>

            <div class="wafer-yield ${isLowYield ? 'low' : ''}">
                ${yieldValue}
            </div>

            <div>${onset}</div>
        `;

        list.appendChild(row);
    });
}

async function openWaferDetail(wafer) {
    selectedWafer = wafer.id;

    let state;

    if (wafer.current) {
        state = latestLiveState;
    } else {
        try {
            const response = await fetch(
                `/api/wafer/${encodeURIComponent(wafer.id)}`
            );

            if (!response.ok) {
                throw new Error('Failed to load wafer details');
            }

            state = await response.json();

        } catch (error) {
            document.getElementById('error').textContent =
                'Unable to load wafer details: ' + error.message;
            return;
        }
    }

    document.getElementById('overview-view').style.display = 'none';
    document.getElementById('detail-view').style.display = 'block';

    const indicator =
        document.getElementById('viewing-indicator');

    if (indicator) {
        indicator.textContent =
            wafer.current
                ? `Viewing Live Wafer: ${wafer.wafer}`
                : `Viewing Saved Wafer: ${wafer.wafer}`;
    }

    renderDashboardState(state);
}

function backToOverview() {
    selectedWafer = null;

    document.getElementById('detail-view').style.display = 'none';
    document.getElementById('overview-view').style.display = 'block';

    if (latestLiveState) {
        renderWaferOverview(latestLiveState);
    }
}

function renderCriteria(criteria) {
    if (!criteria || criteria.length === 0) return;

    const config = {
        mean_trend: {
            valueId: 'criteria-mean-value',
            thresholdId: 'criteria-mean-threshold',
            barId: 'criteria-mean-bar',
            overId: 'criteria-mean-over'
        },
        site_unbalance: {
            valueId: 'criteria-site-value',
            thresholdId: 'criteria-site-threshold',
            barId: 'criteria-site-bar',
            overId: 'criteria-site-over'
        },
        stdev_up: {
            valueId: 'criteria-stdev-value',
            thresholdId: 'criteria-stdev-threshold',
            barId: 'criteria-stdev-bar',
            overId: 'criteria-stdev-over'
        },
        yield: {
            valueId: 'criteria-yield-value',
            thresholdId: 'criteria-yield-threshold',
            barId: 'criteria-yield-bar',
            overId: 'criteria-yield-over'
        }
    };

    criteria.forEach(item => {
        const setting = config[item.key];
        if (!setting) return;

        const valueElement = document.getElementById(setting.valueId);
        const thresholdElement = document.getElementById(setting.thresholdId);
        const leftArea = document.getElementById(setting.barId);
        const rightArea = document.getElementById(setting.overId);

        if (!valueElement || !thresholdElement || !leftArea || !rightArea) return;


        if (item.key === 'yield' && item.enough_data === false) {
            valueElement.textContent = '樣本不足';
            thresholdElement.textContent = '-';

            leftArea.style.width = '100%';
            leftArea.style.background = '#f3f4f6';
            rightArea.style.width = '0%';

            const bar = leftArea.parentElement;
            const thresholdLine = bar.querySelector('.criteria-threshold-line');
            if (thresholdLine) thresholdLine.style.display = 'none';

            const marker = bar.querySelector('.criteria-current-marker');
            if (marker) marker.style.display = 'none';

            return;
        }

        const bar = leftArea.parentElement;
        const thresholdLine = bar.querySelector('.criteria-threshold-line');
        if (thresholdLine) thresholdLine.style.display = '';

        const oldMarker = bar.querySelector('.criteria-current-marker');
        if (oldMarker) oldMarker.style.display = '';
                

        // Display values
        if (item.key === 'yield') {
            valueElement.textContent = item.value != null ? `${(item.value * 100).toFixed(1)}%` : '-';
            thresholdElement.textContent = item.threshold != null ? `${(item.threshold * 100).toFixed(0)}%` : '-';
        } else {
            valueElement.textContent = item.value != null ? `${item.value} tests` : '-';
            thresholdElement.textContent = item.threshold != null ? item.threshold : '-';
        }

        if (item.value == null || item.threshold == null) return;

        // Calculate scale
        let valuePosition;
        let thresholdPosition;

        if (item.key === 'yield') {
            valuePosition = item.value * 100;
            thresholdPosition = item.threshold * 100;
        } else {
            const maxValue = Math.max(item.value * 1.1, item.threshold / 0.8);
            valuePosition = (item.value / maxValue) * 100;
            thresholdPosition = (item.threshold / maxValue) * 100;
        }

        valuePosition = Math.max(0, Math.min(valuePosition, 100));
        if (item.key === 'yield') {
            thresholdPosition = Math.max(0, Math.min(thresholdPosition, 100));
        } else {
            thresholdPosition = Math.max(0, Math.min(thresholdPosition, 80));
        }

        // Good / bad background
        leftArea.style.width = `${thresholdPosition}%`;
        rightArea.style.left = `${thresholdPosition}%`;
        rightArea.style.width = `${100 - thresholdPosition}%`;

        if (item.key === 'yield') {
            leftArea.style.background = '#fee2e2';
            rightArea.style.background = '#dcfce7';
        } else {
            leftArea.style.background = '#dcfce7';
            rightArea.style.background = '#fee2e2';
        }

        // Threshold
        thresholdLine.style.left = `${thresholdPosition}%`;

        // Current value
        let marker = bar.querySelector('.criteria-current-marker');

        if (!marker) {
            marker = document.createElement('div');
            marker.className = 'criteria-current-marker';
            bar.appendChild(marker);
        }

        marker.style.left = `${valuePosition}%`;
    });
}

function renderTDSiteHeatmap(waferMap) {
    const heatmap = document.getElementById('td-site-heatmap');
    if (!heatmap) return;

    heatmap.innerHTML = '';

    const corner = document.createElement('div');
    heatmap.appendChild(corner);

    for (let site = 1; site <= 4; site++) {
        const label = document.createElement('div');
        label.className = 'heatmap-label';
        label.textContent = `Site ${site}`;
        heatmap.appendChild(label);
    }

    const rows = waferMap?.rows || [];
    const maxTD = rows.length > 0 ? Math.max(...rows.map(row => row[0])) : 0;

    for (let td = 1; td <= maxTD; td++) {
        const tdLabel = document.createElement('div');
        tdLabel.className = 'heatmap-label';
        tdLabel.textContent = `TD ${td}`;
        heatmap.appendChild(tdLabel);

        for (let site = 1; site <= 4; site++) {
            const cell = document.createElement('div');
            cell.className = 'heatmap-cell';

            const die = rows.find(row => row[0] === td && row[1] === site);

            if (die) {
                const passed = die[5];
                const suspect = die[6];

                if (suspect) {
                    cell.classList.add('suspect');
                } else if (!passed) {
                    cell.classList.add('failed');
                } else {
                    cell.classList.add('passed');
                }
            }

            cell.dataset.td = td;
            cell.dataset.site = site;
            heatmap.appendChild(cell);
        }
    }
}


async function updateDashboard() {
    try {
        const response = await fetch('/api/state');

        if (!response.ok) {
            throw new Error(
                'Failed to load dashboard state'
            );
        }

        const liveState = await response.json();

        latestLiveState = liveState;

        renderWaferOverview(liveState);

        const detailView =
            document.getElementById('detail-view');

        const detailIsOpen =
            detailView?.style.display !== 'none';

        if (detailIsOpen && selectedWafer) {

            const liveWafer =
                (liveState.wafers || [])
                    .find(wafer =>
                        wafer.id === selectedWafer &&
                        wafer.current
                    );

            if (liveWafer) {
                renderDashboardState(liveState);
            }

        }

        document.getElementById('error').textContent = '';

    } catch (error) {
        document.getElementById('error').textContent =
            'Dashboard update failed: ' +
            error.message;
    }
}

function renderPrediction(predictions, predictorError) {

    const valueElement =
        document.getElementById('temperature-value');

    const statusElement =
        document.getElementById('temperature-status');

    const siteElements = {
        1: document.getElementById('temperature-site-1'),
        2: document.getElementById('temperature-site-2'),
        3: document.getElementById('temperature-site-3'),
        4: document.getElementById('temperature-site-4')
    };


    function resetSites() {
        for (let site = 1; site <= 4; site++) {
            if (siteElements[site]) {
                siteElements[site].textContent = '-- °C';
            }
        }
    }


    if (!valueElement || !statusElement) {
        return;
    }


    if (predictorError) {

        valueElement.textContent = '-- °C';

        resetSites();

        statusElement.textContent =
            `Prediction error: ${predictorError}`;

        return;
    }


    if (!predictions || predictions.length === 0) {

        valueElement.textContent = '-- °C';

        resetSites();

        statusElement.textContent =
            'Waiting for prediction...';

        return;
    }


    const prediction =
        predictions[predictions.length - 1];

    const values =
        prediction.values || {};


    // 每個 Site 的 prediction
    for (let site = 1; site <= 4; site++) {

        const value =
            values[String(site)];

        if (!siteElements[site]) {
            continue;
        }

        if (value == null) {
            siteElements[site].textContent =
                '-- °C';
        } else {
            siteElements[site].textContent =
                `${Number(value).toFixed(1)} °C`;
        }
    }


    // 計算目前有資料的 Site 平均值
    const availableValues =
        Object.values(values)
            .filter(value => value != null)
            .map(Number);


    if (availableValues.length === 0) {

        valueElement.textContent = '-- °C';

        statusElement.textContent =
            `TD ${prediction.td}: prediction unavailable`;

        return;
    }


    const average =
        availableValues.reduce(
            (sum, value) => sum + value,
            0
        ) / availableValues.length;


    valueElement.textContent =
        `${average.toFixed(1)} °C`;


    const statusParts = [];

    statusParts.push(
        `TD ${prediction.td}`
    );


    if (prediction.ready) {
        statusParts.push(
            'All sites ready'
        );
    } else {
        statusParts.push(
            `${prediction.missing} input(s) missing`
        );
    }


    if (prediction.latency_ms != null) {
        statusParts.push(
            `${prediction.latency_ms.toFixed(2)} ms`
        );
    }


    statusElement.textContent =
        statusParts.join(' · ');
}

function renderDashboardState(state) {

    renderPrediction(
        state.predictions,
        state.predictor_error
    );

    const waferSummary =
        state.criteria
            ? null
            : (state.wafers || []).find(
                wafer =>
                    wafer.current &&
                    wafer.wafer === state.wafer
            );

    const criteria =
        state.criteria ??
        waferSummary?.criteria ??
        state.indicators ??
        [];

    renderCriteria(criteria);


    // Top status cards
    document.getElementById('lot').textContent =
        state.lot ?? '-';

    document.getElementById('wafer').textContent =
        state.wafer ?? '-';

    document.getElementById('touchdown').textContent =
        state.touchdown ?? 0;


    // Triggered detector indicators
    const triggeredCriteria =
        (state.indicators || [])
            .filter(item => item.triggered);


    // Overall wafer status
    const anomalyLabel =
        state.headline ??
        state.label ??
        'Normal';

    const hasAttention =
        (state.indicators || []).some(item => item.triggered);

    const hasAnomaly = hasAttention;

    const overallStatus =
        document.getElementById('overall-status');

    const statusWafer =
        document.getElementById('status-wafer');

    const statusTitle =
        document.getElementById('status-title');

    const statusDescription =
        document.getElementById('status-description');


    statusWafer.textContent =
        state.wafer ?? '-';


    if (hasAttention) {

        overallStatus.classList.add('anomaly');

        statusTitle.textContent =
            'Attention Needed';

        statusDescription.textContent =
            'Anomalies detected on this wafer.';

    } else {

        overallStatus.classList.remove('anomaly');

        statusTitle.textContent =
            'No Attention Needed';

        statusDescription.textContent =
            'No anomalies detected on this wafer.';
    }


    const reportNormal =
        document.getElementById('report-normal');
    const reportAnomaly =
        document.getElementById('report-anomaly');

    const reportTitle =
        document.getElementById('report-title');

    const reportDescription =
        document.getElementById('report-description');


    if (hasAnomaly) {
        reportNormal.style.display = 'none';
        reportAnomaly.style.display = 'flex';

        reportTitle.textContent =
            anomalyLabel;

        reportDescription.textContent =
            'The detector identified an abnormal production pattern.';


        const onsetValues =
            triggeredCriteria
                .map(item => item.detail?.onset_td)
                .filter(value => value != null);

        const firstOnset =
            onsetValues.length > 0
                ? Math.min(...onsetValues)
                : null;


        document.getElementById('affected-sites').textContent =
            firstOnset != null
                ? `Detected from Touchdown ${firstOnset}`
                : 'Detected anomaly';


        document.getElementById('detail-touchdown').textContent =
            firstOnset ?? '-';

        document.getElementById('detail-alert-count').textContent =
            triggeredCriteria.length;


        const alertList =
            document.getElementById('alert-list');

        alertList.innerHTML = '';


        triggeredCriteria.forEach(item => {
            const card =
                document.createElement('div');

            card.className = 'alert-detail-card';

            const direction =
                item.detail?.direction ?? '-';

            const group =
                item.detail?.group ?? '-';

            const onset =
                item.detail?.onset_td ?? '-';

            card.innerHTML = `
                <div class="alert-detail-header">
                    <strong>${item.name}</strong>
                </div>

                <div class="alert-detail-meta">
                    <span>Value: ${item.value ?? '-'}</span>
                    <span>Threshold: ${item.threshold ?? '-'}</span>
                    <span>Direction: ${direction}</span>
                    <span>Group: ${group}</span>
                    <span>Onset: TD ${onset}</span>
                </div>
            `;

            alertList.appendChild(card);
        });

    } else {
        reportNormal.style.display = 'block';
        reportAnomaly.style.display = 'none';
    }


    renderTimeline(state.wafer_map, state.touchdown, state.indicators);
    renderWaferMap(state.wafer_map);
    renderSiteOverview(state.wafer_map);
    renderTDSiteHeatmap(state.wafer_map);


    const warningBox =
        document.getElementById('warning');

    const loadError = state.error;

    if (loadError) {
        warningBox.style.display = 'block';

        warningBox.textContent =
            'Detector Warning: ' + loadError;
    } else {
        warningBox.style.display = 'none';
    }
}


const aiButton =
    document.getElementById('ai-button');

const aiBox =
    document.getElementById('ai-box');

const aiClose =
    document.getElementById('ai-close');


aiButton.addEventListener('click', () => {
    aiBox.classList.toggle('open');
});


aiClose.addEventListener('click', () => {
    aiBox.classList.remove('open');
});

const aiInput =
    document.getElementById('ai-input');

const aiSend =
    document.getElementById('ai-send');

const aiMessages =
    document.getElementById('ai-messages');


function addAIMessage(text, type) {

    const message =
        document.createElement('div');

    message.className =
        `ai-message ${type}`;

    message.textContent = text;

    aiMessages.appendChild(message);

    aiMessages.scrollTop =
        aiMessages.scrollHeight;
}

async function sendAIMessage() {

    const question =
        aiInput.value.trim();

    if (!question) {
        return;
    }

    addAIMessage(question, 'user');

    aiInput.value = '';

    addAIMessage(
        'Thinking...',
        'assistant'
    );

    const thinkingMessage =
        aiMessages.lastElementChild;

    try {

        const response = await fetch('/api/chat', {
            method: 'POST',

            headers: {
                'Content-Type': 'application/json'
            },

            body: JSON.stringify({
                question: question
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.error || 'AI request failed'
            );
        }

        thinkingMessage.textContent =
            data.answer;

    } catch (error) {

        thinkingMessage.textContent =
            'Unable to get an AI response: ' +
            error.message;

    }

    aiMessages.scrollTop =
        aiMessages.scrollHeight;
}


aiSend.addEventListener('click', sendAIMessage);


aiInput.addEventListener('keydown', event => {

    if (event.key === 'Enter') {
        sendAIMessage();
    }

});

document
    .querySelectorAll('.ai-suggestion')
    .forEach(button => {

        button.addEventListener('click', () => {

            aiInput.value =
                button.textContent.trim();

            sendAIMessage();

        });

    });

document
    .querySelectorAll('.site-item')
    .forEach(item => {

        const site = Number(item.dataset.site);

        item.addEventListener('mouseenter', () => {

            // 已經固定 Site 時，不接受 hover
            if (selectedSite !== null) {
                return;
            }

            hoveredSite = site;
            updateWaferHighlight();
        });

        item.addEventListener('mouseleave', () => {

            // 已經固定 Site 時，不接受 hover
            if (selectedSite !== null) {
                return;
            }

            hoveredSite = null;
            updateWaferHighlight();
        });

        item.addEventListener('click', () => {

            hoveredSite = null;

            if (selectedSite === site) {
                // 再點一次目前 Site → 取消
                selectedSite = null;
            } else {
                // 固定新的 Site
                selectedSite = site;
            }

            updateSiteSelection();
            updateWaferHighlight();
        });
    });

document.getElementById('back-to-overview')?.addEventListener('click', backToOverview);

const emailInput = document.getElementById('notification-email');
const saveEmailButton = document.getElementById('save-email');
const emailStatus = document.getElementById('email-status');

saveEmailButton?.addEventListener('click', async () => {
    const email = emailInput.value.trim();

    if (!email) {
        emailStatus.textContent = 'Please enter an email.';
        return;
    }

    if (!emailInput.checkValidity()) {
        emailStatus.textContent = 'Invalid email.';
        return;
    }

    try {
        const response = await fetch('/api/email', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email: email })
        });

        if (!response.ok) throw new Error('Failed to save email.');

        emailStatus.textContent = 'Saved';
    } catch (error) {
        emailStatus.textContent = 'Failed to save';
    }
});

async function loadNotificationEmail() {
    try {
        const response = await fetch('/api/email');
        if (!response.ok) return;

        const data = await response.json();

        if (emailInput && data.email) {
            emailInput.value = data.email;
        }
    } catch (error) {
        console.error('Failed to load notification email:', error);
    }
}

loadNotificationEmail();


updateDashboard();

setInterval(updateDashboard, 1000);
