"""Dashboard AstroShield — Streamlit, branché sur le warehouse SQLite.

    streamlit run src/dashboard.py

Fonctionnalités :
1. 🛡️ Veille risque & Alerte planétaire (KPIs, passages rapprochés en LD, énergie Mt TNT)
2. 🔬 Caractérisation physique & Dynamique orbitale (Apollo/Aten/Amor, familles spectrales C/S/M)
3. 💥 Simulateur d'impact & Cratère (calculatrice physique d'impact terrestre)
4. 🤖 Modèles Machine Learning (Random Forest, Gradient Boosting, Isolation Forest)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "astroshield.db"
REPORT_PATH = ROOT / "reports" / "run_report.json"
MODELS_DIR = ROOT / "data" / "models"

st.set_page_config(
    page_title="AstroShield — Observatoire NEO & Risque Planétaire",
    page_icon="☄️",
    layout="wide",
)

st.title("☄️ AstroShield — Observatoire des objets géocroiseurs (NEO)")
st.caption("Plateforme d'analyse astrophysique, d'évaluation de risque d'impact et de Machine Learning")


@st.cache_data(ttl=60)
def load(table: str) -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql(f"SELECT * FROM {table}", con)
    finally:
        con.close()


@st.cache_data(ttl=60)
def load_report() -> dict:
    if REPORT_PATH.exists():
        try:
            return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


report = load_report()

# Barre latérale : état de santé du pipeline et profiling
with st.sidebar:
    st.header("⚙️ Contrôle Qualité & Pipeline")
    if report:
        st_color = "🟢" if report.get("quality_status") == "PASS" else ("🟡" if "WARNING" in report.get("quality_status", "") else "🔴")
        st.markdown(f"### Statut : {st_color} `{report.get('quality_status', 'N/A')}`")
        st.write(f"**Mode d'exécution :** `{report.get('mode', 'N/A')}`")

        c_a, c_b = st.columns(2)
        c_a.metric("Entrées", f"{report.get('input_rows', 0):,}")
        c_b.metric("Acceptées", f"{report.get('accepted_rows', 0):,}")

        c_c, c_d = st.columns(2)
        c_c.metric("Rejets", f"{report.get('rejected_rows', 0):,}")
        c_d.metric("Doublons", f"{report.get('duplicates_removed', 0):,}")

        profiling = report.get("profiling", {})
        if profiling and "health_score_pct" in profiling:
            st.metric("Score de santé des données", f"{profiling['health_score_pct']} %")

        st.caption(f"Durée : {report.get('duration_seconds', 0)} s • Idempotence vérifiée")
    else:
        st.info("Aucun rapport d'exécution trouvé. Lancez d'abord : `python -m src.pipeline --synthetic`")

    st.markdown("---")
    st.markdown("### 🪐 Éphémérides & Références")
    st.markdown("- **1 UA** = 149 597 871 km")
    st.markdown("- **1 LD** (Distance Lunaire) = 384 400 km")
    st.markdown("- **Seuil PHA** : MOID < 0.05 UA & $H \\le 22.0$")

try:
    risk = load("mart_risk_daily")
    charac = load("mart_characterization")
    approaches = load("neo_approaches")
except Exception as e:
    st.error(f"Erreur lors de la lecture de la base SQLite : {e}")
    st.stop()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🛡️ Veille Risque & Alerte",
    "🔬 Caractérisation & Dynamique",
    "💥 Simulateur d'impact & Cratère",
    "🤖 Modèles Machine Learning",
    "📡 Flux Live & WebSockets",
])

# -------------------------------------------------------------
# TAB 1 : VEILLE RISQUE & ALERTE
# -------------------------------------------------------------
with tab1:
    k1, k2, k3, k4 = st.columns(4)
    min_dist_km = risk["min_miss_km"].min()
    min_dist_ld = (min_dist_km / 384400.0) if min_dist_km else 0
    k1.metric("Approches enregistrées", int(risk["neo_count"].sum()))
    k2.metric("Objets PHA sous surveillance", int(charac["is_pha"].sum()))
    k3.metric("Distance minimale", f"{min_dist_ld:.1f} LD", f"{min_dist_km:,.0f} km")
    max_tnt = risk["max_tnt_megatons"].max() if "max_tnt_megatons" in risk.columns else 0
    k4.metric("Énergie d'impact max", f"{max_tnt:,.0f} Mt TNT")

    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("Nombre d'astéroïdes par jour (Total vs Dangereux PHA)")
        st.bar_chart(risk.set_index("approach_date")[["neo_count", "pha_count"]])
    with col_r:
        st.subheader("Distance minimale de passage (en Distances Lunaires LD)")
        if "min_miss_ld" in risk.columns:
            st.line_chart(risk.set_index("approach_date")["min_miss_ld"])
        else:
            st.line_chart(risk.set_index("approach_date")["min_miss_km"])

    st.subheader("Tableau de bord quotidien (Data Mart Gold : mart_risk_daily)")
    st.dataframe(risk, use_container_width=True)

# -------------------------------------------------------------
# TAB 2 : CARACTÉRISATION & DYNAMIQUE ORBITALE
# -------------------------------------------------------------
with tab2:
    st.subheader("Distribution astrophysique et classification dynamique")

    col_dyn, col_spec = st.columns(2)
    with col_dyn:
        if "dynamical_class" in charac.columns:
            st.write("**Classes Dynamiques (Apollo, Amor, Aten, Atira)**")
            dyn_counts = charac["dynamical_class"].value_counts(dropna=False).rename("Astéroïdes")
            st.bar_chart(dyn_counts)
    with col_spec:
        if "spectral_family" in charac.columns:
            st.write("**Familles Spectrales Déduites de l'Albédo**")
            spec_counts = charac["spectral_family"].value_counts(dropna=False).rename("Effectif")
            st.bar_chart(spec_counts)

    if "hazard_level" in charac.columns:
        st.write("**Niveau de dangerosité opérationnelle**")
        st.dataframe(
            charac["hazard_level"].value_counts().reset_index().rename(columns={"index": "Niveau", "hazard_level": "Effectif"}),
            use_container_width=True,
        )

    st.subheader("Carte des astéroïdes surveillés (mart_characterization)")
    pha_filter = st.checkbox("Afficher uniquement les astéroïdes PHA", value=False)
    sub_charac = charac[charac["is_pha"] == 1] if pha_filter else charac

    plot_df = sub_charac.copy()
    plot_df["avg_diameter_km"] = plot_df["avg_diameter_km"].fillna(0.5)
    st.scatter_chart(
        plot_df,
        x="observation_count",
        y="min_miss_km",
        size="avg_diameter_km",
        color="is_pha",
    )
    st.dataframe(sub_charac.sort_values("min_miss_km"), use_container_width=True)

# -------------------------------------------------------------
# TAB 3 : SIMULATEUR D'IMPACT & CRATÈRE TERRESTRE
# -------------------------------------------------------------
with tab3:
    st.subheader("💥 Simulateur d'impact cinétique & calcul de cratère")
    st.markdown("Ce simulateur modélise l'impact théorique d'un astéroïde du catalogue selon les lois d'échelle de **Schmidt-Holsapple**.")

    catalog_names = charac["name"].dropna().unique().tolist()
    if not catalog_names:
        catalog_names = ["(Astéroïde par défaut)"]

    sim_col1, sim_col2 = st.columns(2)
    with sim_col1:
        chosen_name = st.selectbox("Sélectionner un astéroïde dans le catalogue :", catalog_names)
        chosen_obj = charac[charac["name"] == chosen_name].iloc[0] if (charac["name"] == chosen_name).any() else None

        default_d = float(chosen_obj["avg_diameter_km"]) if (chosen_obj is not None and pd.notna(chosen_obj.get("avg_diameter_km"))) else 0.40
        diam_input = st.slider("Diamètre du projectile (km)", min_value=0.01, max_value=15.0, value=min(max(round(default_d, 2), 0.01), 15.0), step=0.05)

        vel_input = st.slider("Vitesse d'impact (km/s)", min_value=11.2, max_value=72.0, value=20.0, step=0.5)

    with sim_col2:
        target_type = st.radio("Type de cible terrestre :", ["Socle rocheux cristallin", "Sédiments / Sols meubles", "Océan profond"])
        target_rho = 2700.0 if "rocheux" in target_type else (1800.0 if "Sédiments" in target_type else 1000.0)

        # Calcul physique
        proj_vol = (4.0 / 3.0) * np.pi * ((diam_input * 1000.0 / 2.0) ** 3)
        proj_mass = proj_vol * 2600.0  # kg
        ke_joules = 0.5 * proj_mass * ((vel_input * 1000.0) ** 2)
        megatons = ke_joules / 4.184e15
        hiroshima_equiv = megatons / 0.015

        # Schmidt-Holsapple : D_cratere ~ 1.15 * (diam)^0.78 * (v)^0.44
        crater_km = 1.15 * (diam_input ** 0.78) * (vel_input ** 0.44) * (2600.0 / target_rho) ** 0.33
        magnitude_mw = round(0.67 * np.log10(max(ke_joules, 1.0)) - 5.87, 1)

    st.markdown("---")
    st.markdown("### 📊 Résultats de la simulation d'impact")
    res1, res2, res3, res4 = st.columns(4)
    res1.metric("Énergie cinétique", f"{megatons:,.1f} Mt", f"{hiroshima_equiv:,.0f} bombes d'Hiroshima")
    res2.metric("Diamètre du cratère", f"{crater_km:.2f} km")
    res3.metric("Séisme induit équivalent", f"{magnitude_mw} Mw")

    # Échelle de Turin
    if megatons < 1:
        torino = 0
        desc = "Zone blanche : Risque nul ou quasi nul."
    elif megatons < 100:
        torino = 3
        desc = "Zone jaune : Passage rapproché méritant l'attention des astronomes."
    elif megatons < 10000:
        torino = 6
        desc = "Zone orange : Menace critique avec dévastation régionale étendue."
    else:
        torino = 9
        desc = "Zone rouge : Catastrophe planétaire et bouleversement climatique global."
    res4.metric("Indice Échelle de Turin", f"{torino} / 10", desc)

    if crater_km > 10.0:
        st.error(f"⚠️ **Conséquences globales** : Cratère de {crater_km:.1f} km. Éjection massive de poussières dans la stratosphère et hiver d'impact.")
    elif crater_km > 1.0:
        st.warning(f"⚠️ **Conséquences régionales** : Cratère de {crater_km:.1f} km. Onde de choc destructrice à des centaines de kilomètres.")
    else:
        st.info(f"ℹ️ **Impact localisé** : Explosion aérienne majeure de type Toungouska ou Tcheliabinsk.")

# -------------------------------------------------------------
# TAB 4 : MODÈLES MACHINE LEARNING & DÉTECTION D'ANOMALIES
# -------------------------------------------------------------
with tab4:
    st.subheader("Modèles de Machine Learning & Détection d'Anomalies Orbitale")
    clf_path = MODELS_DIR / "hazard_classifier.joblib"
    reg_path = MODELS_DIR / "diameter_regressor.joblib"
    iso_path = MODELS_DIR / "orbital_anomalies.joblib"

    if not clf_path.exists():
        st.info("Modèles non trouvés. Lancez : `python -m src.pipeline --synthetic`.")
    else:
        m1, m2, m3 = st.tabs([
            "1. Classification PHA (Random Forest)",
            "2. Régression Diamètre (Gradient Boosting)",
            "3. Détection d'anomalies (Isolation Forest)",
        ])

        with m1:
            st.markdown("**Modèle de référence : Détection du statut PHA (Baseline JPL)**")
            model = joblib.load(clf_path)
            clf = model.named_steps["clf"]
            feats = list(getattr(clf, "feature_names_in_", []))
            if feats:
                importances = pd.Series(clf.feature_importances_, index=feats).sort_values(ascending=True)
                st.write("**Importance relative des variables astronomiques :**")
                st.bar_chart(importances)
            st.json(report.get("ml", {}).get("hazard_classifier", {}))

        with m2:
            st.markdown("**Imputation du diamètre à partir de la magnitude absolue $H$ et de l'albédo**")
            if reg_path.exists():
                reg_model = joblib.load(reg_path)
                st.write("Testez la prédiction de diamètre :")
                rc1, rc2 = st.columns(2)
                h_val = rc1.slider("Magnitude absolue H", 12.0, 30.0, 22.0, 0.1)
                alb_val = rc2.slider("Albédo", 0.02, 0.50, 0.15, 0.01)
                pred_diam = reg_model.predict(pd.DataFrame([{"absolute_magnitude_h": h_val, "albedo": alb_val}]))[0]
                st.metric("Diamètre prédit", f"{pred_diam:.3f} km")
                st.json(report.get("ml", {}).get("diameter_regressor", {}))

        with m3:
            st.markdown("**Détection d'orbites atypiques ou déviantes (Isolation Forest)**")
            if iso_path.exists():
                iso_model = joblib.load(iso_path)
                iso_meta = report.get("ml", {}).get("orbital_anomalies", {})
                st.json(iso_meta)
                st.success(f"Modèle actif : {iso_meta.get('anomalies_detected', 0)} orbites suspectes détectées (taux de contamination = 5 %).")

# -------------------------------------------------------------
# TAB 5 : FLUX LIVE & WEBSOCKETS (SÉANCE 3)
# -------------------------------------------------------------
with tab5:
    st.subheader("📡 Réception télémétrique en direct via WebSocket")
    st.markdown("""
    Ce module connecte l'observatoire au **serveur WebSocket temps réel** (`ws://127.0.0.1:8765`), 
    qui diffuse les flux d'observations télescopiques et les alertes d'impact à haute fréquence (< 5 s).
    """)

    ws_url = st.text_input("URL du serveur WebSocket :", value="ws://127.0.0.1:8765")
    c_btn1, c_btn2 = st.columns(2)

    if "stream_events" not in st.session_state:
        st.session_state["stream_events"] = []

    def fetch_ws_events(url: str, n_events: int = 5, inject_threat: bool = False) -> list[dict]:
        import asyncio
        import websockets

        async def _run():
            evts = []
            async with websockets.connect(url, open_timeout=2.0) as ws:
                # ignore welcome msg
                await ws.recv()
                if inject_threat:
                    await ws.send(json.dumps({"action": "inject_threat"}))
                for _ in range(n_events):
                    msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    evts.append(json.loads(msg))
            return evts

        return asyncio.run(_run())

    with c_btn1:
        if st.button("🔴 Capturer 5 événements en direct via WebSocket"):
            with st.spinner("Connexion au WebSocket et capture du flux..."):
                try:
                    captured = fetch_ws_events(ws_url, n_events=5)
                    st.session_state["stream_events"] = captured + st.session_state["stream_events"]
                    st.success(f"✅ {len(captured)} événements capturés avec succès !")
                except Exception as err:
                    st.error(f"Impossible de joindre le serveur WebSocket sur `{ws_url}` : {err}")
                    st.info("💡 Pour lancer le serveur : ouvrez un terminal et exécutez `python -m src.stream_server`.")

    with c_btn2:
        if st.button("🚨 Injecter une alerte critique en direct"):
            with st.spinner("Envoi du paquet d'alerte critique sur le WebSocket..."):
                try:
                    threat_evts = fetch_ws_events(ws_url, n_events=1, inject_threat=True)
                    st.session_state["stream_events"] = threat_evts + st.session_state["stream_events"]
                    st.warning("⚠️ Alerte critique injectée et diffusée à tous les clients !")
                except Exception as err:
                    st.error(f"Erreur WebSocket : {err}")
                    st.info("💡 Lancez d'abord le serveur : `python -m src.stream_server`")

    # Affichage des événements reçus
    events = st.session_state["stream_events"]
    if events:
        st.markdown("---")
        st.markdown(f"### 📋 Derniers flux reçus ({len(events)} observations)")

        # Alerte d'urgence si menace
        criticals = [e for e in events if e.get("alert")]
        if criticals:
            latest = criticals[0]
            st.error(
                f"🚨 **DÉFENSE PLANÉTAIRE ACTIVE** : Astéroïde **{latest.get('name')}** "
                f"à seulement **{latest.get('lunar_distance_ld')} LD** "
                f"({latest.get('miss_distance_km'):,.0f} km) ! "
                f"Énergie : {latest.get('tnt_megatons'):,.0f} Mt TNT | Échelle de Turin : {latest.get('torino_scale')}/10"
            )

        events_df = pd.DataFrame(events)
        cols_show = [c for c in [
            "event_id", "occurred_at", "name", "lunar_distance_ld", "miss_distance_km",
            "relative_velocity_kms", "diameter_km", "tnt_megatons", "torino_scale", "alert"
        ] if c in events_df.columns]
        st.dataframe(events_df[cols_show], use_container_width=True)

        if st.button("Effacer l'historique du flux"):
            st.session_state["stream_events"] = []
            st.rerun()
    else:
        st.info("Aucun événement dans le buffer actuel. Cliquez sur le bouton ci-dessus pour capturer le flux.")

    st.markdown("---")
    st.subheader("🔭 Scraper Temps Réel — IAU Minor Planet Center & NASA CNEOS")
    st.markdown("""
    Scrape en direct les nouveaux candidats astéroïdes détectés par les télescopes de surveillance optique 
    du monde entier (*Pan-STARRS*, *Catalina Sky Survey*, *ATLAS*) publiés sur le **NEOCP** (*Near-Earth Object Confirmation Page*).
    """)

    try:
        from src.realtime_scraper import scrape_mpc_neocp, scrape_cneos_live
    except ImportError:
        from realtime_scraper import scrape_mpc_neocp, scrape_cneos_live

    col_sc1, col_sc2 = st.columns(2)
    with col_sc1:
        if st.button("🛰️ Scraper les nouvelles découvertes MPC (En direct)"):
            with st.spinner("Scraping en cours depuis minorplanetcenter.net..."):
                mpc_data = scrape_mpc_neocp()
                if mpc_data:
                    st.session_state["mpc_live"] = mpc_data
                    st.success(f"✅ {len(mpc_data)} candidats astéroïdes géocroiseurs actifs extraits !")
                else:
                    st.warning("Aucune donnée extraite ou serveur temporairement indisponible.")

    with col_sc2:
        if st.button("🪐 Scraper les approches imminentes NASA CNEOS"):
            with st.spinner("Interrogation de l'API live CNEOS..."):
                cneos_data = scrape_cneos_live(limit=10)
                if cneos_data:
                    st.session_state["cneos_live"] = cneos_data
                    st.success(f"✅ {len(cneos_data)} approches imminentes récupérées !")
                else:
                    st.warning("Aucune approche trouvée.")

    if "mpc_live" in st.session_state and st.session_state["mpc_live"]:
        st.markdown("#### 🚨 Candidats astéroïdes détectés aujourd'hui (MPC NEOCP)")
        mpc_df = pd.DataFrame(st.session_state["mpc_live"])
        st.dataframe(
            mpc_df[["temp_id", "neo_score_pct", "observation_epoch", "apparent_v_magnitude", "estimated_diameter_m", "urgency", "ra_hours", "dec_degrees"]],
            use_container_width=True,
        )

    if "cneos_live" in st.session_state and st.session_state["cneos_live"]:
        st.markdown("#### 🌍 Approches terrestres imminentes (NASA JPL CNEOS)")
        cneos_df = pd.DataFrame(st.session_state["cneos_live"])
        st.dataframe(
            cneos_df[["name", "approach_datetime_utc", "lunar_distance_ld", "miss_distance_km", "relative_velocity_kms", "estimated_diameter_km", "is_potentially_hazardous"]],
            use_container_width=True,
        )


