/**
 * ASTROSHIELD — Moteur Frontend JavaScript Temps Réel
 * 
 * Stack purement JS :
 * 1. Visualiseur 3D WebGL Spatial (Three.js + OrbitControls)
 * 2. Radar Géocentrique Tactique 2D (HTML5 Canvas 60 FPS)
 * 3. Moteur Graphique Télémétrique (Chart.js synchronisé)
 * 4. Simulateur Physique d'Impact (Schmidt-Holsapple)
 * 5. Flux WebSocket Haute Cadence & Scraper Autonome (Zéro bouton requis)
 * 6. Synthétiseur Sonore de Défense Planétaire (Web Audio API)
 */

// ============================================================================
// 1. État Global de l'Application
// ============================================================================

const STATE = {
  socket: null,
  socketConnected: false,
  reconnectAttempts: 0,
  audioEnabled: true,
  audioCtx: null,
  viewMode: '3d', // '3d' ou '2d'
  radarTargets: [],
  lockedTarget: null,
  radarAngle: 0,
  activeFilter: 'all',
  allRecords: [],
  maxTorino: 0,
  maxEnergyMt: 0,
  maxVelocityKms: 0,
  eventCount: 0,
  // Three.js instances
  threeScene: null,
  threeCamera: null,
  threeRenderer: null,
  threeControls: null,
  threeAsteroidsGroup: null,
  threeEarth: null,
  threeMoon: null,
  threeRaycaster: null,
  threeMouse: null,
  // Chart.js instances
  velocityChart: null,
  distanceChart: null,
};

// ============================================================================
// 2. Synthétiseur Audio Web Audio API (Planetary Defense Acoustic Synth)
// ============================================================================

function initAudioContext() {
  if (!STATE.audioCtx) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (AudioContextClass) {
      STATE.audioCtx = new AudioContextClass();
    }
  }
}

function playRadarBeep(freq = 880, duration = 0.07) {
  if (!STATE.audioEnabled) return;
  try {
    initAudioContext();
    if (!STATE.audioCtx) return;
    const osc = STATE.audioCtx.createOscillator();
    const gain = STATE.audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, STATE.audioCtx.currentTime);
    gain.gain.setValueAtTime(0.03, STATE.audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, STATE.audioCtx.currentTime + duration);
    osc.connect(gain);
    gain.connect(STATE.audioCtx.destination);
    osc.start();
    osc.stop(STATE.audioCtx.currentTime + duration);
  } catch (e) {}
}

function playDefenseAlertSiren() {
  if (!STATE.audioEnabled) return;
  try {
    initAudioContext();
    if (!STATE.audioCtx) return;
    const now = STATE.audioCtx.currentTime;
    const osc = STATE.audioCtx.createOscillator();
    const gain = STATE.audioCtx.createGain();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(440, now);
    osc.frequency.linearRampToValueAtTime(880, now + 0.25);
    osc.frequency.linearRampToValueAtTime(440, now + 0.5);
    gain.gain.setValueAtTime(0.1, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
    osc.connect(gain);
    gain.connect(STATE.audioCtx.destination);
    osc.start(now);
    osc.stop(now + 0.55);
  } catch (e) {}
}

// ============================================================================
// 3. Horloge UTC & Contrôles En-tête
// ============================================================================

function startUtcClock() {
  const clockEl = document.getElementById('utcClock');
  function update() {
    const now = new Date();
    clockEl.textContent = now.toISOString().substring(11, 19) + ' UTC';
  }
  update();
  setInterval(update, 1000);
}

function setupHeaderControls() {
  const audioBtn = document.getElementById('audioToggleBtn');
  const audioIcon = document.getElementById('audioIcon');
  const audioLabel = document.getElementById('audioLabel');

  audioBtn.addEventListener('click', () => {
    initAudioContext();
    STATE.audioEnabled = !STATE.audioEnabled;
    if (STATE.audioEnabled) {
      audioIcon.textContent = '🔊';
      audioLabel.textContent = 'AUDIO ACTIF';
      audioBtn.classList.remove('hud-btn-danger');
      playRadarBeep(980, 0.1);
    } else {
      audioIcon.textContent = '🔇';
      audioLabel.textContent = 'MUET';
      audioBtn.classList.add('hud-btn-danger');
    }
  });

  const drillBtn = document.getElementById('drillBtn');
  drillBtn.addEventListener('click', () => {
    initAudioContext();
    if (STATE.socket && STATE.socket.readyState === WebSocket.OPEN) {
      STATE.socket.send(JSON.stringify({ action: 'trigger_threat' }));
    } else {
      fetch('/api/simulate-threat', { method: 'POST' }).catch(() => {});
    }
  });

  // Bascule Mode 2D / 3D
  const btn3D = document.getElementById('viewMode3D');
  const btn2D = document.getElementById('viewMode2D');
  const threeCont = document.getElementById('threeContainer');
  const canvas2D = document.getElementById('radarCanvas');

  btn3D.addEventListener('click', () => {
    STATE.viewMode = '3d';
    btn3D.classList.add('active');
    btn2D.classList.remove('active');
    threeCont.classList.remove('hidden');
    canvas2D.classList.add('hidden');
    if (STATE.threeRenderer) {
      const rect = threeCont.getBoundingClientRect();
      STATE.threeRenderer.setSize(rect.width, rect.height);
      STATE.threeCamera.aspect = rect.width / rect.height;
      STATE.threeCamera.updateProjectionMatrix();
    }
  });

  btn2D.addEventListener('click', () => {
    STATE.viewMode = '2d';
    btn2D.classList.add('active');
    btn3D.classList.remove('active');
    canvas2D.classList.remove('hidden');
    threeCont.classList.add('hidden');
  });
}

function dismissBanner() {
  const banner = document.getElementById('planetaryAlertBanner');
  if (banner) banner.classList.add('hidden');
}

// ============================================================================
// 4. Moteur 3D WebGL Spatial (Three.js)
// ============================================================================

function initThreeScene() {
  const container = document.getElementById('threeContainer');
  if (!container || typeof THREE === 'undefined') return;

  const width = container.clientWidth || 700;
  const height = container.clientHeight || 480;

  // 1. Scène et Caméra
  STATE.threeScene = new THREE.Scene();
  STATE.threeScene.background = new THREE.Color(0x050814);
  STATE.threeScene.fog = new THREE.FogExp2(0x050814, 0.007);

  STATE.threeCamera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  STATE.threeCamera.position.set(0, 45, 75);

  // 2. Rendu WebGL
  STATE.threeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  STATE.threeRenderer.setSize(width, height);
  STATE.threeRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(STATE.threeRenderer.domElement);

  // 3. Contrôles Orbitaux (Rotation interactive à la souris)
  if (typeof THREE.OrbitControls !== 'undefined') {
    STATE.threeControls = new THREE.OrbitControls(STATE.threeCamera, STATE.threeRenderer.domElement);
    STATE.threeControls.enableDamping = true;
    STATE.threeControls.dampingFactor = 0.05;
    STATE.threeControls.maxDistance = 180;
    STATE.threeControls.minDistance = 15;
  }

  // 4. Éclairage
  const ambientLight = new THREE.AmbientLight(0x223355, 1.2);
  STATE.threeScene.add(ambientLight);

  const sunLight = new THREE.DirectionalLight(0xffffff, 1.8);
  sunLight.position.set(80, 50, 60);
  STATE.threeScene.add(sunLight);

  // 5. La Terre (Centre 0, 0, 0)
  const earthGeo = new THREE.SphereGeometry(4.0, 32, 32);
  const earthMat = new THREE.MeshPhongMaterial({
    color: 0x1d4ed8,
    emissive: 0x0a1c44,
    specular: 0x38bdf8,
    shininess: 25,
    wireframe: false,
  });
  STATE.threeEarth = new THREE.Mesh(earthGeo, earthMat);
  STATE.threeScene.add(STATE.threeEarth);

  // Atmosphère externe de la Terre
  const atmosGeo = new THREE.SphereGeometry(4.35, 32, 32);
  const atmosMat = new THREE.MeshBasicMaterial({
    color: 0x00f0ff,
    transparent: true,
    opacity: 0.18,
    side: THREE.BackSide,
  });
  const atmosMesh = new THREE.Mesh(atmosGeo, atmosMat);
  STATE.threeEarth.add(atmosMesh);

  // 6. Orbites et Anneaux (1 LD = 12 unités 3D)
  // 1 LD = 12, 5 LD = 30, 19.5 LD = 75
  const createOrbitRing = (radius, colorHex, opacity = 0.4, dashed = false) => {
    const segments = 96;
    const geom = new THREE.BufferGeometry();
    const positions = [];
    for (let i = 0; i <= segments; i++) {
      const theta = (i / segments) * Math.PI * 2;
      positions.push(Math.cos(theta) * radius, 0, Math.sin(theta) * radius);
    }
    geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    const mat = new THREE.LineBasicMaterial({ color: colorHex, transparent: true, opacity });
    return new THREE.Line(geom, mat);
  };

  const lunarOrbitRing = createOrbitRing(12, 0x00ff88, 0.6);
  STATE.threeScene.add(lunarOrbitRing);

  const dangerRing = createOrbitRing(30, 0xffb700, 0.45);
  STATE.threeScene.add(dangerRing);

  const phaRing = createOrbitRing(75, 0xff2a5f, 0.35);
  STATE.threeScene.add(phaRing);

  // 7. La Lune
  const moonGeo = new THREE.SphereGeometry(1.0, 24, 24);
  const moonMat = new THREE.MeshStandardMaterial({ color: 0xcccccc, roughness: 0.8 });
  STATE.threeMoon = new THREE.Mesh(moonGeo, moonMat);
  STATE.threeScene.add(STATE.threeMoon);

  // 8. Groupe des Astéroïdes
  STATE.threeAsteroidsGroup = new THREE.Group();
  STATE.threeScene.add(STATE.threeAsteroidsGroup);

  // 9. Raycaster pour interaction clic/survol sur les objets 3D
  STATE.threeRaycaster = new THREE.Raycaster();
  STATE.threeMouse = new THREE.Vector2();

  container.addEventListener('click', (e) => {
    const rect = container.getBoundingClientRect();
    STATE.threeMouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    STATE.threeMouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    STATE.threeRaycaster.setFromCamera(STATE.threeMouse, STATE.threeCamera);
    const intersects = STATE.threeRaycaster.intersectObjects(STATE.threeAsteroidsGroup.children, true);

    if (intersects.length > 0) {
      const clickedMesh = intersects[0].object;
      if (clickedMesh.userData && clickedMesh.userData.target) {
        lockRadarTarget(clickedMesh.userData.target);
      }
    }
  });

  // Redimensionnement fluide
  window.addEventListener('resize', () => {
    if (!container || !STATE.threeRenderer || !STATE.threeCamera) return;
    const w = container.clientWidth;
    const h = container.clientHeight;
    STATE.threeCamera.aspect = w / h;
    STATE.threeCamera.updateProjectionMatrix();
    STATE.threeRenderer.setSize(w, h);
  });

  // Boucle d'animation 60 FPS
  let moonAngle = 0;
  function animateThree() {
    requestAnimationFrame(animateThree);

    // Rotation de la Terre sur son axe
    if (STATE.threeEarth) {
      STATE.threeEarth.rotation.y += 0.003;
    }

    // Orbite de la Lune (1 LD = 12 unités)
    if (STATE.threeMoon) {
      moonAngle += 0.005;
      STATE.threeMoon.position.set(Math.cos(moonAngle) * 12, 0, Math.sin(moonAngle) * 12);
    }

    // Animation pulsante des astéroïdes 3D
    if (STATE.threeAsteroidsGroup) {
      const time = Date.now() * 0.003;
      STATE.threeAsteroidsGroup.children.forEach(ast => {
        ast.rotation.y += 0.01;
        if (ast.userData && ast.userData.halo) {
          const s = 1.0 + Math.sin(time + ast.userData.offset) * 0.2;
          ast.userData.halo.scale.set(s, s, s);
        }
      });
    }

    if (STATE.threeControls) {
      STATE.threeControls.update();
    }

    if (STATE.viewMode === '3d') {
      STATE.threeRenderer.render(STATE.threeScene, STATE.threeCamera);
    }
  }

  animateThree();
}

function updateThreeAsteroids() {
  if (!STATE.threeAsteroidsGroup) return;

  // Vider le groupe actuel
  while (STATE.threeAsteroidsGroup.children.length > 0) {
    const obj = STATE.threeAsteroidsGroup.children[0];
    STATE.threeAsteroidsGroup.remove(obj);
  }

  // Échelle 3D : 1 LD = 12 unités, max à 80
  STATE.radarTargets.forEach((tgt, idx) => {
    const dist3D = Math.min(80, Math.max(8, (tgt.dist_ld / 40.0) * 80));
    const angle = tgt.angle;
    const elevation = ((idx % 5) - 2) * 4; // Dispersion képlérienne 3D

    const x = Math.cos(angle) * dist3D;
    const y = elevation;
    const z = Math.sin(angle) * dist3D;

    // Couleur selon criticité
    let colorHex = 0x00ff88;
    if (tgt.dist_ld < 1.0 || tgt.torino >= 3) {
      colorHex = 0xff2a5f;
    } else if (tgt.dist_ld < 5.0 || tgt.is_pha) {
      colorHex = 0xffb700;
    }

    // Astéroïde 3D Mesh
    const astSize = Math.max(0.6, Math.min(2.5, tgt.diameter_km * 3.0));
    const astGeo = new THREE.DodecahedronGeometry(astSize, 1);
    const astMat = new THREE.MeshStandardMaterial({
      color: colorHex,
      roughness: 0.5,
      metalness: 0.3,
      emissive: colorHex,
      emissiveIntensity: 0.4,
    });
    const astMesh = new THREE.Mesh(astGeo, astMat);
    astMesh.position.set(x, y, z);
    astMesh.userData = { target: tgt, offset: idx };

    // Halo lumineux externe
    const haloGeo = new THREE.SphereGeometry(astSize * 1.6, 16, 16);
    const haloMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.25,
      side: THREE.BackSide,
    });
    const haloMesh = new THREE.Mesh(haloGeo, haloMat);
    astMesh.add(haloMesh);
    astMesh.userData.halo = haloMesh;

    // Ligne de vecteur vitesse reliant vers la Terre
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(x, y, z),
      new THREE.Vector3(x * 0.85, y * 0.85, z * 0.85),
    ]);
    const lineMat = new THREE.LineBasicMaterial({ color: colorHex, transparent: true, opacity: 0.4 });
    const vectorLine = new THREE.Line(lineGeo, lineMat);

    STATE.threeAsteroidsGroup.add(astMesh);
    STATE.threeAsteroidsGroup.add(vectorLine);
  });
}

// ============================================================================
// 5. Radar Géocentrique Tactique 2D (Canvas)
// ============================================================================

function initRadarCanvas() {
  const canvas = document.getElementById('radarCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  function resize() {
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width || 700;
    canvas.height = rect.height || 480;
  }
  resize();
  window.addEventListener('resize', resize);

  canvas.addEventListener('click', (e) => {
    const rect = canvas.getBoundingClientRect();
    const cx = canvas.width / 2;
    const cy = canvas.height / 2;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const maxR = Math.min(cx, cy) * 0.92;

    let clicked = null;
    STATE.radarTargets.forEach(tgt => {
      const r = (Math.min(tgt.dist_ld, 40) / 40) * maxR;
      const tx = cx + Math.cos(tgt.angle) * r;
      const ty = cy + Math.sin(tgt.angle) * r;
      const dist = Math.hypot(mx - tx, my - ty);
      if (dist < 15) {
        clicked = tgt;
      }
    });

    if (clicked) {
      lockRadarTarget(clicked);
    }
  });

  function draw() {
    if (STATE.viewMode === '2d') {
      const w = canvas.width;
      const h = canvas.height;
      const cx = w / 2;
      const cy = h / 2;
      const maxR = Math.min(cx, cy) * 0.92;

      ctx.clearRect(0, 0, w, h);

      // Cercles concentriques
      const rings = [
        { ld: 1.0, color: 'rgba(0, 255, 136, 0.5)', label: '1.0 LD (Orbite Lune)' },
        { ld: 5.0, color: 'rgba(255, 183, 0, 0.4)', label: '5.0 LD (Zone Vigilance)', dashed: true },
        { ld: 19.5, color: 'rgba(255, 42, 95, 0.35)', label: '19.5 LD (Seuil PHA 0.05 AU)' },
        { ld: 40.0, color: 'rgba(0, 240, 255, 0.2)', label: '40.0 LD (Limite Portée)' },
      ];

      rings.forEach(ring => {
        const r = (ring.ld / 40.0) * maxR;
        ctx.beginPath();
        if (ring.dashed) ctx.setLineDash([4, 4]);
        else ctx.setLineDash([]);
        ctx.strokeStyle = ring.color;
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();

        ctx.fillStyle = ring.color;
        ctx.font = '9px "Share Tech Mono"';
        ctx.fillText(ring.label, cx + 8, cy - r + 11);
      });
      ctx.setLineDash([]);

      // Faisceau balayage radar
      STATE.radarAngle = (STATE.radarAngle + 0.02) % (Math.PI * 2);

      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, maxR);
      grad.addColorStop(0, 'rgba(0, 240, 255, 0)');
      grad.addColorStop(1, 'rgba(0, 240, 255, 0.16)');

      ctx.save();
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, maxR, STATE.radarAngle - 0.25, STATE.radarAngle);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(STATE.radarAngle) * maxR, cy + Math.sin(STATE.radarAngle) * maxR);
      ctx.strokeStyle = 'rgba(0, 240, 255, 0.8)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.restore();

      // Terre au centre
      const earthR = Math.max(10, maxR * 0.06);
      ctx.beginPath();
      ctx.arc(cx, cy, earthR, 0, Math.PI * 2);
      ctx.fillStyle = '#1d4ed8';
      ctx.fill();
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 9px "Orbitron"';
      ctx.textAlign = 'center';
      ctx.fillText('TERRE', cx, cy + 3);

      // Cibles
      STATE.radarTargets.forEach(tgt => {
        const r = (Math.min(tgt.dist_ld, 40) / 40) * maxR;
        const tx = cx + Math.cos(tgt.angle) * r;
        const ty = cy + Math.sin(tgt.angle) * r;

        let color = '#00ff88';
        if (tgt.dist_ld < 1.0 || tgt.torino >= 3) color = '#ff2a5f';
        else if (tgt.dist_ld < 5.0 || tgt.is_pha) color = '#ffb700';

        ctx.beginPath();
        ctx.arc(tx, ty, 4, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        ctx.fillStyle = '#ffffff';
        ctx.font = '9px "Share Tech Mono"';
        ctx.textAlign = 'left';
        ctx.fillText(`${tgt.name} (${tgt.dist_ld} LD)`, tx + 8, ty - 4);
      });
    }

    requestAnimationFrame(draw);
  }

  requestAnimationFrame(draw);
}

function lockRadarTarget(target) {
  STATE.lockedTarget = target;
  const card = document.getElementById('radarTargetCard');
  if (!card) return;

  card.classList.remove('hidden');
  document.getElementById('targetName').textContent = target.name;
  document.getElementById('targetDist').textContent = `${target.dist_ld} LD (${Math.round(target.dist_km).toLocaleString()} km)`;
  document.getElementById('targetVel').textContent = `${target.velocity_kms} km/s`;
  document.getElementById('targetDiam').textContent = `${Math.round(target.diameter_km * 1000)} m`;
  document.getElementById('targetTorino').textContent = `Niveau ${target.torino}`;
}

function loadLockedTargetToSim() {
  if (!STATE.lockedTarget) return;
  const diamM = Math.round(STATE.lockedTarget.diameter_km * 1000);
  const velKms = Math.round(STATE.lockedTarget.velocity_kms);

  document.getElementById('simDiam').value = diamM;
  document.getElementById('simVel').value = velKms;
  document.getElementById('simDiamVal').textContent = diamM;
  document.getElementById('simVelVal').textContent = velKms;

  calculateImpactPhysics();
  document.querySelector('.panel-physics').scrollIntoView({ behavior: 'smooth' });
}

// ============================================================================
// 6. Graphiques Télémétriques Chart.js
// ============================================================================

function initCharts() {
  if (typeof Chart === 'undefined') return;

  // Configuration générale Chart.js pour thème sombre
  Chart.defaults.color = '#8b9bb4';
  Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.06)';
  Chart.defaults.font.family = "'Share Tech Mono', monospace";

  // 1. Graphique des vitesses
  const ctxVel = document.getElementById('velocityChart');
  if (ctxVel) {
    STATE.velocityChart = new Chart(ctxVel, {
      type: 'bar',
      data: {
        labels: ['< 15 km/s', '15-20 km/s', '20-25 km/s', '25-30 km/s', '> 30 km/s'],
        datasets: [{
          label: 'Objets Détectés',
          data: [4, 12, 18, 8, 3],
          backgroundColor: 'rgba(0, 240, 255, 0.45)',
          borderColor: '#00f0ff',
          borderWidth: 1.5,
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, grid: { color: 'rgba(255, 255, 255, 0.05)' } },
          x: { grid: { display: false } },
        },
      },
    });
  }

  // 2. Graphique des distances
  const ctxDist = document.getElementById('distanceChart');
  if (ctxDist) {
    STATE.distanceChart = new Chart(ctxDist, {
      type: 'line',
      data: {
        labels: ['#1', '#2', '#3', '#4', '#5', '#6', '#7', '#8', '#9', '#10'],
        datasets: [{
          label: 'Distance de passage (LD)',
          data: [1.2, 4.5, 12.0, 18.2, 2.1, 8.4, 24.5, 0.9, 15.0, 31.0],
          borderColor: '#00ff88',
          backgroundColor: 'rgba(0, 255, 136, 0.1)',
          fill: true,
          tension: 0.35,
          pointBackgroundColor: '#00ff88',
          pointRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, grid: { color: 'rgba(255, 255, 255, 0.05)' } },
          x: { grid: { display: false } },
        },
      },
    });
  }
}

function updateCharts() {
  if (!STATE.velocityChart || !STATE.distanceChart) return;

  // Calcul histogramme vitesses
  const bins = [0, 0, 0, 0, 0];
  STATE.allRecords.forEach(r => {
    const v = parseFloat(r.velocity_kms) || 20;
    if (v < 15) bins[0]++;
    else if (v < 20) bins[1]++;
    else if (v < 25) bins[2]++;
    else if (v < 30) bins[3]++;
    else bins[4]++;
  });

  STATE.velocityChart.data.datasets[0].data = bins;
  STATE.velocityChart.update('none');

  // Dernières 10 distances
  const last10 = STATE.allRecords.slice(0, 10);
  if (last10.length > 0) {
    STATE.distanceChart.data.labels = last10.map(r => r.name.substring(0, 8));
    STATE.distanceChart.data.datasets[0].data = last10.map(r => parseFloat(r.dist_ld) || 10);
    STATE.distanceChart.update('none');
  }
}

// ============================================================================
// 7. Simulateur Physique Schmidt-Holsapple
// ============================================================================

function setupPhysicsSimulator() {
  const diamInput = document.getElementById('simDiam');
  const velInput = document.getElementById('simVel');
  const angleInput = document.getElementById('simAngle');
  const targetSelect = document.getElementById('simTargetType');

  function update() {
    document.getElementById('simDiamVal').textContent = diamInput.value;
    document.getElementById('simVelVal').textContent = velInput.value;
    document.getElementById('simAngleVal').textContent = angleInput.value;
    calculateImpactPhysics();
  }

  diamInput.addEventListener('input', update);
  velInput.addEventListener('input', update);
  angleInput.addEventListener('input', update);
  targetSelect.addEventListener('change', update);

  calculateImpactPhysics();
}

function calculateImpactPhysics() {
  const d_m = parseFloat(document.getElementById('simDiam').value);
  const v_kms = parseFloat(document.getElementById('simVel').value);
  const angleDeg = parseFloat(document.getElementById('simAngle').value);
  const targetType = document.getElementById('simTargetType').value;

  const v_ms = v_kms * 1000;
  const rad = angleDeg * (Math.PI / 180);

  const rho_proj = 2600.0;
  let rho_target = 2700.0;
  if (targetType === 'sedimentary') rho_target = 2400.0;
  if (targetType === 'water') rho_target = 1000.0;

  // 1. Énergie cinétique
  const volume = (4 / 3) * Math.PI * Math.pow(d_m / 2, 3);
  const mass_kg = volume * rho_proj;
  const energy_j = 0.5 * mass_kg * Math.pow(v_ms, 2);
  const energy_mt = energy_j / 4.184e15;

  // 2. Schmidt-Holsapple Cratère
  const g = 9.81;
  const d_tc_m = 1.161 * Math.pow(rho_proj / rho_target, 0.33) * Math.pow(g, -0.22) * Math.pow(d_m, 0.78) * Math.pow(v_ms, 0.44) * Math.pow(Math.sin(rad), 0.33);
  const d_final_km = (d_tc_m * 1.25) / 1000;
  const depth_m = d_final_km > 3.2 ? d_final_km * 250 : d_tc_m / 3;

  // 3. Magnitude Sismique
  const seismic_mw = Math.min(10.5, Math.max(1.0, 0.67 * Math.log10(energy_j) - 5.87));

  // 4. Onde de choc
  const blast_radius_km = 0.28 * Math.pow(energy_mt, 1 / 3);

  document.getElementById('outEnergyMt').textContent = `${energy_mt.toLocaleString(undefined, { maximumFractionDigits: 1 })} Mt`;
  document.getElementById('outEnergyJoules').textContent = `${energy_j.toExponential(2)} Joules`;

  let comp = 'Hiroshima (0.015 Mt)';
  if (energy_mt > 50000000) comp = 'Impact Chicxulub (Extinction)';
  else if (energy_mt > 50) comp = 'Tsar Bomba (50 Mt)';
  else if (energy_mt > 1) comp = 'Bombe thermonucléaire B83';
  document.getElementById('outEnergyComp').textContent = `Équivalence : ${comp}`;

  document.getElementById('outCraterKm').textContent = `${d_final_km.toFixed(2)} km`;
  document.getElementById('outCraterDepth').textContent = `Profondeur estimée : ${Math.round(depth_m).toLocaleString()} m`;

  document.getElementById('outSeismicMag').textContent = `M ${seismic_mw.toFixed(1)}`;
  document.getElementById('outSeismicDesc').textContent = seismic_mw > 7 ? 'Séisme dévastateur majeur' : 'Secousses modérées';

  document.getElementById('outBlastRadius').textContent = `${blast_radius_km.toFixed(1)} km`;
}

// ============================================================================
// 8. WebSocket & Flux Scraping Temps Réel (ZÉRO BOUTON REQUIS)
// ============================================================================

function connectWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${location.host}/ws`;
  const statusEl = document.getElementById('socketStatus');

  try {
    STATE.socket = new WebSocket(wsUrl);

    STATE.socket.onopen = () => {
      STATE.socketConnected = true;
      STATE.reconnectAttempts = 0;
      if (statusEl) {
        statusEl.textContent = 'WS: CONNECTÉ';
        statusEl.className = 'tag-status tag-online';
      }
      addTerminalRow('SYS', 'Connecté au flux WebSocket AstroShield en direct.', 'badge-cneos');
    };

    STATE.socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleIncomingEvent(data);
      } catch (err) {
        console.error('Erreur décodage message WS:', err);
      }
    };

    STATE.socket.onclose = () => {
      STATE.socketConnected = false;
      if (statusEl) {
        statusEl.textContent = 'WS: RECONNEXION...';
        statusEl.className = 'tag-status';
      }
      const delay = Math.min(5000, 1000 * Math.pow(1.5, STATE.reconnectAttempts++));
      setTimeout(connectWebSocket, delay);
    };

    STATE.socket.onerror = () => {
      if (STATE.socket) STATE.socket.close();
    };
  } catch (err) {
    console.error('Exception connexion WebSocket:', err);
    setTimeout(connectWebSocket, 3000);
  }
}

async function loadInitialState() {
  try {
    const res = await fetch('/api/initial-state');
    if (!res.ok) return;
    const data = await res.json();

    if (data.mpc_candidates && data.mpc_candidates.length > 0) {
      document.getElementById('kpiMpcCount').textContent = data.mpc_candidates.length;
      data.mpc_candidates.forEach(cand => {
        addRecordToStore({
          id: cand.temp_id,
          name: cand.name,
          source: 'MPC NEOCP',
          dist_ld: 12.5,
          dist_km: 4805000,
          velocity_kms: 21.0,
          diameter_km: cand.estimated_diameter_m / 1000,
          tnt_mt: 450,
          crater_km: 1.8,
          torino: cand.neo_score_pct >= 80 ? 2 : 0,
          is_pha: cand.neo_score_pct >= 80,
          date: cand.observation_epoch,
        });
      });
    }

    if (data.cneos_approaches && data.cneos_approaches.length > 0) {
      document.getElementById('kpiCneosCount').textContent = data.cneos_approaches.length;
      const closest = data.cneos_approaches[0];
      if (closest) {
        document.getElementById('kpiClosestDist').textContent = `Plus proche : ${closest.lunar_distance_ld} LD`;
      }
      data.cneos_approaches.forEach(app => {
        addRecordToStore({
          id: app.designation,
          name: app.name,
          source: 'NASA CNEOS',
          dist_ld: app.lunar_distance_ld,
          dist_km: app.miss_distance_km,
          velocity_kms: app.relative_velocity_kms,
          diameter_km: app.estimated_diameter_km,
          tnt_mt: app.tnt_megatons,
          crater_km: app.crater_diameter_km,
          torino: app.torino_scale,
          is_pha: app.is_potentially_hazardous,
          date: app.approach_datetime_utc,
        });
      });
    }

    if (data.database_approaches && data.database_approaches.length > 0) {
      data.database_approaches.forEach(dbRow => {
        addRecordToStore({
          id: dbRow.neo_id,
          name: dbRow.name,
          source: 'Base AstroShield',
          dist_ld: dbRow.lunar_distance_ld || (dbRow.miss_distance_km / 384400).toFixed(2),
          dist_km: dbRow.miss_distance_km,
          velocity_kms: dbRow.relative_velocity_kms,
          diameter_km: dbRow.diameter_mid_km,
          tnt_mt: dbRow.tnt_megatons || 120,
          crater_km: dbRow.crater_diameter_km || 1.2,
          torino: dbRow.torino_scale || 0,
          is_pha: !!dbRow.is_potentially_hazardous,
          date: dbRow.approach_date,
        });
      });
    }

    updateKPIs();
    renderTable();
    updateCharts();
  } catch (e) {
    console.warn('Impossible de charger initial-state:', e);
  }
}

function handleIncomingEvent(evt) {
  STATE.eventCount++;
  document.getElementById('terminalCounter').textContent = `${STATE.eventCount} ÉVÉNEMENTS`;
  const timeStr = new Date().toISOString().substring(11, 19);

  if (evt.event_type === 'scraper.mpc_discovery') {
    addTerminalRow(
      timeStr,
      `Découverte MPC : <strong>${evt.name}</strong> | Score: ${evt.neo_score}% | Mag V: ${evt.magnitude} | Ø: ${evt.diameter_m}m`,
      evt.alert ? 'badge-alert' : 'badge-mpc'
    );

    addRecordToStore({
      id: evt.temp_id,
      name: evt.name,
      source: 'MPC NEOCP',
      dist_ld: (Math.random() * 25 + 2).toFixed(2),
      dist_km: Math.round((Math.random() * 25 + 2) * 384400),
      velocity_kms: (Math.random() * 20 + 12).toFixed(1),
      diameter_km: (evt.diameter_m / 1000).toFixed(3),
      tnt_mt: Math.round(Math.pow(evt.diameter_m / 50, 3) * 10),
      crater_km: (Math.pow(evt.diameter_m / 1000, 0.78) * 2.2).toFixed(2),
      torino: evt.alert ? 2 : 0,
      is_pha: evt.alert,
      date: new Date().toISOString().substring(0, 10),
    });

    if (evt.alert) playDefenseAlertSiren();
    else playRadarBeep(720, 0.06);
  } else if (evt.event_type === 'scraper.cneos_sync') {
    addTerminalRow(
      timeStr,
      `Synchronisation CNEOS : ${evt.approaches_count} approches. Plus proche : ${evt.closest_approach ? evt.closest_approach.name : 'N/A'}`,
      'badge-cneos'
    );
    if (evt.closest_approach) {
      document.getElementById('kpiClosestDist').textContent = `Plus proche : ${evt.closest_approach.lunar_distance_ld} LD`;
    }
  } else if (evt.event_type === 'telescope.radar_ping' || evt.event_type === 'telescope.critical_threat') {
    const isThreat = evt.alert_level === 'CRITICAL' || evt.lunar_distance_ld < 1.0;

    addRadarTarget(evt);
    updateThreeAsteroids();

    addRecordToStore({
      id: evt.event_id || evt.name,
      name: evt.name,
      source: evt.source || 'Radar Terrestre',
      dist_ld: evt.lunar_distance_ld,
      dist_km: evt.miss_distance_km,
      velocity_kms: evt.relative_velocity_kms,
      diameter_km: evt.diameter_km,
      tnt_mt: evt.tnt_megatons,
      crater_km: evt.crater_diameter_km,
      torino: evt.torino_scale,
      is_pha: evt.is_potentially_hazardous,
      date: 'Temps Réel',
    });

    if (isThreat) {
      addTerminalRow(
        timeStr,
        `🚨 MENACE CRITIQUE : <strong>${evt.name}</strong> à ${evt.lunar_distance_ld} LD (${evt.miss_distance_km.toLocaleString()} km) | ${evt.tnt_megatons} Mt TNT`,
        'badge-alert'
      );
      triggerPlanetaryAlertBanner(evt);
      playDefenseAlertSiren();
    } else {
      addTerminalRow(
        timeStr,
        `Contact Radar : <strong>${evt.name}</strong> à ${evt.lunar_distance_ld} LD | Vit: ${evt.relative_velocity_kms} km/s`,
        'badge-radar'
      );
      playRadarBeep(1100, 0.04);
    }
  } else if (evt.event_type === 'telemetry.heartbeat') {
    if (evt.mpc_active_count) document.getElementById('kpiMpcCount').textContent = evt.mpc_active_count;
    if (evt.cneos_active_count) document.getElementById('kpiCneosCount').textContent = evt.cneos_active_count;
  }

  updateKPIs();
  renderTable();
  updateCharts();
}

function addRadarTarget(evt) {
  const angle = (evt.position_angle_deg !== undefined ? evt.position_angle_deg : Math.random() * 360) * (Math.PI / 180);
  const existingIdx = STATE.radarTargets.findIndex(t => t.name === evt.name);

  const target = {
    name: evt.name,
    dist_ld: parseFloat(evt.lunar_distance_ld),
    dist_km: evt.miss_distance_km,
    velocity_kms: evt.relative_velocity_kms,
    diameter_km: evt.diameter_km,
    tnt_mt: evt.tnt_megatons,
    torino: evt.torino_scale,
    is_pha: evt.is_potentially_hazardous,
    angle: angle,
  };

  if (existingIdx >= 0) {
    STATE.radarTargets[existingIdx] = target;
  } else {
    STATE.radarTargets.push(target);
    if (STATE.radarTargets.length > 25) STATE.radarTargets.shift();
  }
}

function triggerPlanetaryAlertBanner(evt) {
  const banner = document.getElementById('planetaryAlertBanner');
  if (banner) {
    banner.classList.remove('hidden');
    banner.querySelector('.alert-text').innerHTML = `
      <strong>ALERTE DÉFENSE PLANÉTAIRE :</strong> Rapprochement critique de <strong>${evt.name}</strong> à seulement ${evt.lunar_distance_ld} LD (${evt.miss_distance_km.toLocaleString()} km) ! Énergie : ${evt.tnt_megatons} Mt TNT.
    `;
  }
}

function addTerminalRow(time, htmlMsg, badgeClass) {
  const stream = document.getElementById('terminalStream');
  if (!stream) return;

  const row = document.createElement('div');
  row.className = 'terminal-row';
  row.innerHTML = `
    <span class="t-time">[${time}]</span>
    <span class="t-badge ${badgeClass}">${badgeClass.replace('badge-', '').toUpperCase()}</span>
    <span class="t-msg">${htmlMsg}</span>
  `;

  stream.prepend(row);
  while (stream.children.length > 100) {
    stream.removeChild(stream.lastChild);
  }
}

function clearTerminal() {
  const stream = document.getElementById('terminalStream');
  if (stream) stream.innerHTML = '';
}

// ============================================================================
// 9. Stockage & Tableau Dynamique
// ============================================================================

function addRecordToStore(rec) {
  const idx = STATE.allRecords.findIndex(r => r.name === rec.name);
  if (idx >= 0) {
    STATE.allRecords[idx] = { ...STATE.allRecords[idx], ...rec };
  } else {
    STATE.allRecords.unshift(rec);
    if (STATE.allRecords.length > 200) STATE.allRecords.pop();
  }

  if (rec.torino > STATE.maxTorino) STATE.maxTorino = rec.torino;
  if (rec.tnt_mt > STATE.maxEnergyMt) STATE.maxEnergyMt = rec.tnt_mt;
  if (rec.velocity_kms > STATE.maxVelocityKms) STATE.maxVelocityKms = rec.velocity_kms;
}

function updateKPIs() {
  const phaCount = STATE.allRecords.filter(r => r.is_pha).length;
  document.getElementById('kpiPhaCount').textContent = phaCount;

  document.getElementById('kpiMaxEnergy').innerHTML = `${STATE.maxEnergyMt.toLocaleString()} <span class="kpi-unit">Mt TNT</span>`;
  document.getElementById('kpiMaxVelocity').innerHTML = `${STATE.maxVelocityKms} <span class="kpi-unit">km/s</span>`;

  updateTorinoDisplay(STATE.maxTorino);

  document.getElementById('countAll').textContent = STATE.allRecords.length;
  document.getElementById('countCrit').textContent = STATE.allRecords.filter(r => r.dist_ld < 5.0).length;
  document.getElementById('countPha').textContent = phaCount;
  document.getElementById('countMpc').textContent = STATE.allRecords.filter(r => r.source.includes('MPC')).length;
}

function updateTorinoDisplay(level) {
  const maxValEl = document.getElementById('torinoMaxVal');
  const titleEl = document.getElementById('torinoTitle');
  const descEl = document.getElementById('torinoDesc');

  if (maxValEl) maxValEl.textContent = level;

  const steps = document.querySelectorAll('.torino-step');
  steps.forEach((st, idx) => {
    if (idx === level) st.classList.add('active');
    else st.classList.remove('active');
  });

  const torinoData = {
    0: { title: "NIVEAU 0 : ÉVÉNEMENT SANS DANGER", desc: "La probabilité de collision est nulle ou négligeable.", color: "#00ff88" },
    1: { title: "NIVEAU 1 : ÉVÉNEMENT NORMAL", desc: "Passage rapproché ordinaire ne posant aucun danger.", color: "#38a169" },
    2: { title: "NIVEAU 2 : ATTENTION REQUISE DES ASTRONOMES", desc: "Objet géocroiseur passant près de la Terre méritant une surveillance.", color: "#ecc94b" },
    3: { title: "NIVEAU 3 : ATTENTION SOUTENUE", desc: "Rencontre rapprochée méritant l'attention des astronomes.", color: "#ecc94b" },
    4: { title: "NIVEAU 4 : RAPPROCHEMENT CRITIQUE", desc: "Objet capable de dévastation régionale.", color: "#d69e2e" },
    5: { title: "NIVEAU 5 : MENACE SÉRIEUSE", desc: "Collision possible pouvant provoquer une dévastation majeure.", color: "#ed8936" },
    8: { title: "NIVEAU 8 : COLLISION CERTAINE (LOCALISÉE)", desc: "Collision inévitable capable de destruction localisée terrestre.", color: "#e53e3e" },
    10: { title: "NIVEAU 10 : CATASTROPHE PLANÉTAIRE GLOBALE", desc: "Collision inévitable d'un impacteur géant.", color: "#ff2a5f" },
  };

  const info = torinoData[level] || torinoData[0];
  if (titleEl) titleEl.textContent = info.title;
  if (descEl) descEl.textContent = info.desc;
  if (maxValEl) {
    maxValEl.style.color = info.color;
    maxValEl.style.textShadow = `0 0 16px ${info.color}`;
  }
}

function setupTableFilters() {
  const filterBtns = document.querySelectorAll('.filter-btn');
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      STATE.activeFilter = btn.dataset.filter;
      renderTable();
    });
  });
}

function renderTable() {
  const tbody = document.getElementById('approachesTableBody');
  if (!tbody) return;

  let records = STATE.allRecords;
  if (STATE.activeFilter === 'critical') records = records.filter(r => r.dist_ld < 5.0);
  else if (STATE.activeFilter === 'pha') records = records.filter(r => r.is_pha);
  else if (STATE.activeFilter === 'mpc') records = records.filter(r => r.source.includes('MPC'));

  tbody.innerHTML = '';
  records.slice(0, 50).forEach(rec => {
    const tr = document.createElement('tr');
    const isCrit = rec.dist_ld < 1.0 || rec.torino >= 3;

    tr.innerHTML = `
      <td><strong>${rec.name}</strong></td>
      <td><span class="badge-hud">${rec.source}</span></td>
      <td>
        <span class="${isCrit ? 'text-danger' : (rec.dist_ld < 5.0 ? 'text-warning' : '')}">
          ${rec.dist_ld} LD (${Math.round(rec.dist_km).toLocaleString()} km)
        </span>
      </td>
      <td>${rec.velocity_kms} km/s</td>
      <td>${Math.round(rec.diameter_km * 1000)} m</td>
      <td>${rec.tnt_mt ? rec.tnt_mt.toLocaleString() + ' Mt' : '--'}</td>
      <td>${rec.crater_km ? rec.crater_km + ' km' : '--'}</td>
      <td>
        <span class="badge-row-tag ${rec.is_pha ? 'tag-pha' : 'tag-safe'}">
          ${rec.torino !== undefined ? 'Turin ' + rec.torino : (rec.is_pha ? 'PHA' : 'Standard')}
        </span>
      </td>
      <td>
        <button class="btn-inspect" onclick="inspectRecord('${rec.name}')">Simuler</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function inspectRecord(name) {
  const rec = STATE.allRecords.find(r => r.name === name);
  if (!rec) return;

  const diamM = Math.round(rec.diameter_km * 1000);
  const velKms = Math.round(rec.velocity_kms);

  document.getElementById('simDiam').value = diamM;
  document.getElementById('simVel').value = velKms;
  document.getElementById('simDiamVal').textContent = diamM;
  document.getElementById('simVelVal').textContent = velKms;

  calculateImpactPhysics();
  document.querySelector('.panel-physics').scrollIntoView({ behavior: 'smooth' });
}

// ============================================================================
// 10. Initialisation au Chargement
// ============================================================================

window.addEventListener('DOMContentLoaded', () => {
  startUtcClock();
  setupHeaderControls();
  initThreeScene();
  initRadarCanvas();
  initCharts();
  setupPhysicsSimulator();
  setupTableFilters();
  loadInitialState();
  connectWebSocket();
});
