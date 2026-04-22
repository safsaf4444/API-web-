/**
 * Seren Phase 5: Statistical Calculator Widget
 * Pure client-side calculations for NNT, OR, and Effect Size (Cohen's d).
 */

(function () {
  // Inject the UI modal into the body
  function injectStatsCalcUI() {
    const html = `
      <div id="statsCalcModal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:9999; align-items:center; justify-content:center;">
        <div style="background:var(--surface); width: 480px; max-width:95vw; border-radius:var(--r); padding:24px; box-shadow:var(--shadow-lg); font-size:14px; max-height:90vh; overflow-y:auto;">
          <div style="font-family:var(--font-display); font-size:20px; font-weight:700; color:var(--navy); margin-bottom:4px; display:flex; justify-content:space-between; align-items:flex-start;">
            Statistical Calculator
            <button id="closeStatsCalcBtn" style="background:none; border:none; cursor:pointer; font-size:20px; line-height:1; padding:0; color:var(--subtle);">&times;</button>
          </div>

          <!-- Info section -->
          <div style="margin-bottom:16px;">
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
              <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--subtle);">What is this?</span>
              <button id="statsCalcInfoToggle" style="font-size:11px;color:var(--brass2);background:none;border:none;padding:0;cursor:pointer;font-weight:600;text-decoration:underline;">Show guide</button>
            </div>
            <div id="statsCalcInfoBox" style="display:none;background:var(--surface2);border:1px solid var(--line);border-radius:var(--r-sm);padding:14px 16px;font-size:12.5px;line-height:1.7;color:var(--text2);margin-bottom:8px;">
              <p style="margin:0 0 10px;font-size:13px;font-weight:600;color:var(--navy);">A bedside clinical statistics toolkit — no software needed.</p>
              <p style="margin:0 0 10px;">Use these calculators to interpret the numbers reported in papers you are reading. All calculations run locally in your browser — nothing is sent to a server.</p>
              <div style="display:flex;flex-direction:column;gap:8px;">
                <div style="padding:10px 12px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r-sm);">
                  <div style="font-weight:700;color:var(--navy);margin-bottom:2px;">NNT &mdash; Number Needed to Treat</div>
                  <div style="color:var(--muted);">How many patients must receive a treatment for one additional patient to benefit, compared to control. Enter the event rate (%) in the experimental group (EER) and in the control group (CER) from the paper's results table. <em>Lower NNT = more effective treatment.</em></div>
                  <div style="margin-top:4px;font-size:11.5px;color:var(--subtle);">Formula: NNT = 1 / |CER − EER|</div>
                </div>
                <div style="padding:10px 12px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r-sm);">
                  <div style="font-weight:700;color:var(--navy);margin-bottom:2px;">Odds Ratio (OR)</div>
                  <div style="color:var(--muted);">The odds of an outcome in the exposed group relative to the unexposed group. Enter the 2×2 contingency table values: exposed cases &amp; controls, unexposed cases &amp; controls. A 95% CI is calculated automatically. <em>OR &gt; 1 = increased odds; OR &lt; 1 = decreased odds; OR = 1 = no effect.</em></div>
                  <div style="margin-top:4px;font-size:11.5px;color:var(--subtle);">Formula: OR = (a×d) / (b×c) &middot; CI via log method</div>
                </div>
                <div style="padding:10px 12px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r-sm);">
                  <div style="font-weight:700;color:var(--navy);margin-bottom:2px;">Effect Size &mdash; Cohen's d</div>
                  <div style="color:var(--muted);">Standardised mean difference between two groups in standard deviation units. Enter the means and standard deviations from both groups. <em>d ≥ 0.2 = small, ≥ 0.5 = medium, ≥ 0.8 = large effect.</em></div>
                  <div style="margin-top:4px;font-size:11.5px;color:var(--subtle);">Formula: d = |M1 − M2| / SD<sub>pooled</sub></div>
                </div>
              </div>
            </div>
          </div>

          <div style="display:flex; gap:10px; margin-bottom:16px;">
            <button class="btn sm primary" id="tabNNT">NNT</button>
            <button class="btn sm ghost" id="tabOR">Odds Ratio</button>
            <button class="btn sm ghost" id="tabSMD">Effect Size</button>
          </div>

          <!-- NNT Calculator -->
          <div id="panelNNT" style="display:block;">
            <label style="display:block; margin-bottom:4px; font-size:12px; color:var(--subtle);">Experimental Event Rate (EER %)</label>
            <input type="number" id="inpEER" placeholder="e.g. 15" style="width:100%; margin-bottom:12px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
            <label style="display:block; margin-bottom:4px; font-size:12px; color:var(--subtle);">Control Event Rate (CER %)</label>
            <input type="number" id="inpCER" placeholder="e.g. 20" style="width:100%; margin-bottom:12px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
            
            <button class="btn" id="btnCalcNNT">Calculate NNT</button>
            <div id="resNNT" style="margin-top:12px; font-weight:600; color:var(--navy);"></div>
          </div>

          <!-- OR Calculator -->
          <div id="panelOR" style="display:none;">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
              <div>
                <label style="font-size:12px; color:var(--subtle);">Exposed Cases</label>
                <input type="number" id="inpExpCases" style="width:100%; margin-bottom:8px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
              </div>
              <div>
                <label style="font-size:12px; color:var(--subtle);">Exposed Controls</label>
                <input type="number" id="inpExpControls" style="width:100%; margin-bottom:8px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
              </div>
              <div>
                <label style="font-size:12px; color:var(--subtle);">Unexposed Cases</label>
                <input type="number" id="inpUnexpCases" style="width:100%; margin-bottom:8px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
              </div>
              <div>
                <label style="font-size:12px; color:var(--subtle);">Unexposed Controls</label>
                <input type="number" id="inpUnexpControls" style="width:100%; margin-bottom:8px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
              </div>
            </div>
            <button class="btn" id="btnCalcOR" style="margin-top:8px;">Calculate Odds Ratio</button>
            <div id="resOR" style="margin-top:12px; font-weight:600; color:var(--navy);"></div>
          </div>

          <!-- SMD Calculator -->
          <div id="panelSMD" style="display:none;">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
              <div>
                <label style="font-size:12px; color:var(--subtle);">Mean (Experimental)</label>
                <input type="number" id="inpMean1" style="width:100%; margin-bottom:8px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
              </div>
              <div>
                <label style="font-size:12px; color:var(--subtle);">Mean (Control)</label>
                <input type="number" id="inpMean2" style="width:100%; margin-bottom:8px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
              </div>
              <div>
                <label style="font-size:12px; color:var(--subtle);">SD (Experimental)</label>
                <input type="number" id="inpSD1" style="width:100%; margin-bottom:8px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
              </div>
              <div>
                <label style="font-size:12px; color:var(--subtle);">SD (Control)</label>
                <input type="number" id="inpSD2" style="width:100%; margin-bottom:8px; padding:6px; border:1px solid var(--line); border-radius:4px;" />
              </div>
            </div>
            <button class="btn" id="btnCalcSMD" style="margin-top:8px;">Calculate Cohen's d</button>
            <div id="resSMD" style="margin-top:12px; font-weight:600; color:var(--navy);"></div>
          </div>

        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    bindEvents();
  }

  function toggleTab(tab) {
    document.getElementById('panelNNT').style.display = tab === 'nnt' ? 'block' : 'none';
    document.getElementById('panelOR').style.display = tab === 'or' ? 'block' : 'none';
    document.getElementById('panelSMD').style.display = tab === 'smd' ? 'block' : 'none';
    
    document.getElementById('tabNNT').className = tab === 'nnt' ? 'btn sm primary' : 'btn sm ghost';
    document.getElementById('tabOR').className = tab === 'or' ? 'btn sm primary' : 'btn sm ghost';
    document.getElementById('tabSMD').className = tab === 'smd' ? 'btn sm primary' : 'btn sm ghost';
  }

  function bindEvents() {
    document.getElementById('closeStatsCalcBtn').onclick = () => {
      document.getElementById('statsCalcModal').style.display = 'none';
    };

    // Close on backdrop click
    document.getElementById('statsCalcModal').addEventListener('click', function(e) {
      if (e.target === this) this.style.display = 'none';
    });

    // Info guide toggle
    document.getElementById('statsCalcInfoToggle').addEventListener('click', function() {
      const box = document.getElementById('statsCalcInfoBox');
      const visible = box.style.display !== 'none';
      box.style.display = visible ? 'none' : 'block';
      this.textContent = visible ? 'Show guide' : 'Hide guide';
    });

    document.getElementById('tabNNT').onclick = () => toggleTab('nnt');
    document.getElementById('tabOR').onclick = () => toggleTab('or');
    document.getElementById('tabSMD').onclick = () => toggleTab('smd');

    // NNT Calculation
    document.getElementById('btnCalcNNT').onclick = () => {
      const eer = parseFloat(document.getElementById('inpEER').value) / 100;
      const cer = parseFloat(document.getElementById('inpCER').value) / 100;
      const res = document.getElementById('resNNT');
      if (isNaN(eer) || isNaN(cer)) {
        res.innerHTML = '<span style="color:var(--bad);">Error: Invalid input rates.</span>';
        return;
      }
      const arr = Math.abs(cer - eer);
      if (arr === 0) {
        res.innerHTML = 'NNT: &#8734; (No absolute risk reduction)';
      } else {
        const nnt = Math.ceil(1 / arr);
        res.innerHTML = `Absolute Risk Reduction: ${(arr * 100).toFixed(2)}%<br><b>NNT = ${nnt}</b>`;
      }
    };

    // OR Calculation
    document.getElementById('btnCalcOR').onclick = () => {
      const a = parseFloat(document.getElementById('inpExpCases').value);
      const b = parseFloat(document.getElementById('inpExpControls').value);
      const c = parseFloat(document.getElementById('inpUnexpCases').value);
      const d = parseFloat(document.getElementById('inpUnexpControls').value);
      const res = document.getElementById('resOR');
      if ([a,b,c,d].some(isNaN) || (b*c) === 0) {
        res.innerHTML = '<span style="color:var(--bad);">Error: Invalid matrix or divide by zero.</span>';
        return;
      }
      const or = (a * d) / (b * c);
      // Rough 95% CI (log method)
      const seLogOR = Math.sqrt((1/a) + (1/b) + (1/c) + (1/d));
      const lowerCI = Math.exp(Math.log(or) - 1.96 * seLogOR);
      const upperCI = Math.exp(Math.log(or) + 1.96 * seLogOR);

      res.innerHTML = `Odds Ratio: <b>${or.toFixed(2)}</b><br><span style="font-size:12px;color:var(--subtle);">95% CI: [${lowerCI.toFixed(2)} - ${upperCI.toFixed(2)}]</span>`;
    };

    // SMD Calculation (Cohen's d)
    document.getElementById('btnCalcSMD').onclick = () => {
      const m1 = parseFloat(document.getElementById('inpMean1').value);
      const m2 = parseFloat(document.getElementById('inpMean2').value);
      const sd1 = parseFloat(document.getElementById('inpSD1').value);
      const sd2 = parseFloat(document.getElementById('inpSD2').value);
      const res = document.getElementById('resSMD');
      
      if ([m1,m2,sd1,sd2].some(isNaN) || sd1 <= 0 || sd2 <= 0) {
        res.innerHTML = '<span style="color:var(--bad);">Error: Invalid parameters (SD must be > 0).</span>';
        return;
      }
      // Pooled standard deviation (assuming equal sample sizes for simplistic demo)
      const sdPooled = Math.sqrt((Math.pow(sd1, 2) + Math.pow(sd2, 2)) / 2);
      const d = Math.abs(m1 - m2) / sdPooled;
      
      let interp = "Small";
      if (d >= 0.8) interp = "Large";
      else if (d >= 0.5) interp = "Medium";

      res.innerHTML = `Cohen's d: <b>${d.toFixed(2)}</b> (${interp} effect size)`;
    };
  }

  // Define global launcher
  window.openStatsCalculator = function() {
    let modal = document.getElementById('statsCalcModal');
    if (!modal) {
      injectStatsCalcUI();
      modal = document.getElementById('statsCalcModal');
    }
    modal.style.display = 'flex';
  };

})();
