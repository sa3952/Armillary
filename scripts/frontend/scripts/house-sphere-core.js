(function attachHouseSphereCore(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.HouseSphereCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildHouseSphereCore() {
  "use strict";

  // 〈宮位制〉文章的天球示意圖用的球面幾何。只收三個數：地理緯度、ARMC（赤經中天，
  // 也就是地方恆星時換成度數）與黃赤交角；不收日期、時刻或地點，所以不可能是誰的命盤。
  // 命盤的宮頭一律由計算服務算；這裡的數字只供示意，CI 逐格對照 Swiss Ephemeris 的
  // houses_armc（tests/publication/test_house_sphere_oracle.py）。
  // 座標：赤道直角座標，x 指向春分點，z 指向北天極；角度一律以「度」進出。

  // 示意圖固定的黃赤交角。命盤用的是出生時刻的真黃赤交角，在 1900 到 2399 年間差不到
  // 0.06 度，對看懂構造沒有影響，少一個控制項。
  const OBLIQUITY = 23.44;
  const D = Math.PI / 180;

  const mod360 = (x) => ((x % 360) + 360) % 360;
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const scale = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const neg = (a) => [-a[0], -a[1], -a[2]];
  function norm(a) {
    const length = Math.hypot(a[0], a[1], a[2]);
    return [a[0] / length, a[1] / length, a[2] / length];
  }

  /** 觀測者的參考向量：天頂、地平正東、地平正北、天赤道在上子午圈的點、北黃極、北天極。 */
  function frame(lat, armc, eps) {
    const p = lat * D;
    const t = armc * D;
    const e = eps * D;
    const zenith = [Math.cos(p) * Math.cos(t), Math.cos(p) * Math.sin(t), Math.sin(p)];
    const east = [-Math.sin(t), Math.cos(t), 0];
    return {
      lat, armc, eps,
      Z: zenith,
      E: east,
      N: cross(zenith, east),
      Meq: [Math.cos(t), Math.sin(t), 0],
      K: [0, -Math.sin(e), Math.cos(e)],
      P: [0, 0, 1],
    };
  }

  function eclVec(lon, eps) {
    const l = lon * D;
    const e = eps * D;
    return [Math.cos(l), Math.sin(l) * Math.cos(e), Math.sin(l) * Math.sin(e)];
  }
  function raDecVec(ra, dec) {
    const a = ra * D;
    const d = dec * D;
    return [Math.cos(d) * Math.cos(a), Math.cos(d) * Math.sin(a), Math.sin(d)];
  }
  /** 黃道上赤經為 ra 的那一點的黃經。 */
  const lonFromRA = (ra, eps) => mod360(Math.atan2(Math.sin(ra * D), Math.cos(ra * D) * Math.cos(eps * D)) / D);
  const decOfLon = (lon, eps) => Math.asin(Math.sin(lon * D) * Math.sin(eps * D)) / D;
  function lonOfVec(v, eps) {
    const e = eps * D;
    return mod360(Math.atan2(v[1] * Math.cos(e) + v[2] * Math.sin(e), v[0]) / D);
  }

  /** 半日弧（度）：這個赤緯從地平升到上中天轉過的角度。整天不升或不落時回 null。 */
  function semiArc(dec, lat) {
    const x = Math.tan(lat * D) * Math.tan(dec * D);
    if (!(Math.abs(x) <= 1)) return null;
    return 90 + Math.asin(x) / D;
  }

  const mcOf = (F) => lonFromRA(F.armc, F.eps);
  /** 上升點：黃道與地平在東半邊的交點。常見的反正切公式在中天沉到地平線下時
   *  會落到西邊那一點，所以用天頂與正東的向量再判一次。 */
  function ascOf(F) {
    const t = F.armc * D;
    const e = F.eps * D;
    const p = F.lat * D;
    const lon = mod360(Math.atan2(Math.cos(t), -(Math.sin(t) * Math.cos(e) + Math.tan(p) * Math.sin(e))) / D);
    return dot(eclVec(lon, F.eps), F.E) < 0 ? mod360(lon + 180) : lon;
  }

  /** 黃道與「通過地平正北、正南兩點並經過 point 的大圓」的交點，取 point 所在的那半圈。 */
  function northSouthCircleCut(F, point) {
    const normal = cross(F.N, point);
    let x = norm(cross(normal, F.K));
    const towards = sub(point, scale(F.N, dot(point, F.N)));
    if (dot(x, towards) < 0) x = neg(x);
    return lonOfVec(x, F.eps);
  }

  // 宮頭 10、11、12、1、2、3 在被分割的圓上的角度：從上子午點起量，向東為正。
  const ALPHA = Object.freeze({ 10: 0, 11: 30, 12: 60, 1: 90, 2: 120, 3: 150 });
  const EASTERN_CUSPS = Object.freeze([10, 11, 12, 1, 2, 3]);

  /** Placidus：這個宮頭的時角是它自己半弧的固定分數。回傳時角（度，向西為正）。 */
  function placidusHourAngle(house, arc) {
    switch (house) {
      case 11: return -arc / 3;
      case 12: return -2 * arc / 3;
      case 2: return 180 + 2 * (180 - arc) / 3;
      case 3: return 180 + (180 - arc) / 3;
      default: throw new Error(`no Placidus hour angle for house ${house}`);
    }
  }

  function placidusCusp(F, house) {
    let lon = lonFromRA(F.armc + ALPHA[house], F.eps);
    for (let step = 0; step < 500; step += 1) {
      const arc = semiArc(decOfLon(lon, F.eps), F.lat);
      if (arc === null) return null;
      const next = lonFromRA(F.armc - placidusHourAngle(house, arc), F.eps);
      const change = Math.abs(((next - lon + 540) % 360) - 180);
      lon = next;
      if (change < 1e-12) return lon;
    }
    return null;
  }

  // 計算頁選單的順序：每宮 30 度兩種，四分宮制依名稱來源人物的年代。
  const SYSTEMS = Object.freeze(["W", "E", "O", "B", "C", "R", "P"]);
  const QUADRANT = Object.freeze(["O", "B", "C", "R", "P"]);

  function mcBelowHorizon(F) {
    return dot(eclVec(mcOf(F), F.eps), F.Z) < 0;
  }

  /**
   * 本站計算服務對同一組緯度與宮位制會給的狀態（四態之一與原因代碼）。
   * 規則照 backend/app/core/houses.py：Placidus 整個極區帶拒收；中天沉到地平線下時
   * Porphyry 與 Alcabitius 拒收，Regiomontanus 與 Campanus 因宮頭不再依序排列也拒收；
   * 四分宮制在緯度 60 度以上標「不穩定」；整宮、等分宮在極區帶標「屬極區幾何」。
   * 服務用的是出生時刻的真黃赤交角，極區帶的邊界因此差不到 0.1 度。
   */
  function siteStatus(sys, lat, armc, eps) {
    const F = frame(lat, armc, eps);
    const band = Math.abs(lat) >= 90 - eps ? "polar" : Math.abs(lat) >= 60 ? "high" : "ordinary";
    const quadrant = QUADRANT.includes(sys);
    if (sys === "P" && band === "polar") return { state: "unavailable", reason: "placidus_no_semiarc" };
    if (quadrant && sys !== "P" && mcBelowHorizon(F)) {
      return { state: "unavailable",
        reason: sys === "O" || sys === "B" ? "mc_below_horizon_rejected" : "degenerate_cusp_cycle_rejected" };
    }
    if (quadrant && band !== "ordinary") return { state: "unstable", reason: "quadrant_high_latitude_sensitivity" };
    if (band === "polar") return { state: "available_polar_geometry", reason: "polar_band_geometry" };
    return { state: "available", reason: null };
  }

  /**
   * 十二宮頭（index 0 是第一宮）。geometry 為 false 表示這種構造在此處沒有解
   * （Placidus 在極區帶）；本站拒收但幾何仍畫得出來的情形，cusps 照給，由 siteStatus 說明。
   */
  function cusps(sys, lat, armc, eps) {
    const F = frame(lat, armc, eps);
    const asc = ascOf(F);
    const mc = mcOf(F);
    const out = new Array(12).fill(null);
    const set = (house, lon) => {
      out[house - 1] = mod360(lon);
      out[(house + 5) % 12] = mod360(lon + 180);
    };
    let geometry = true;
    if (sys === "W") {
      const start = Math.floor(asc / 30) * 30;
      for (let i = 0; i < 12; i += 1) out[i] = mod360(start + 30 * i);
    } else if (sys === "E") {
      for (let i = 0; i < 12; i += 1) out[i] = mod360(asc + 30 * i);
    } else if (sys === "O") {
      const lower = mod360(mc + 180 - asc) / 3;
      const upper = mod360(asc + 180 - (mc + 180)) / 3;
      set(1, asc); set(2, asc + lower); set(3, asc + 2 * lower);
      set(10, mc); set(11, mc + upper); set(12, mc + 2 * upper);
    } else if (sys === "B") {
      const arc = semiArc(decOfLon(asc, eps), lat);
      if (arc === null) geometry = false;
      else {
        set(10, mc); set(1, asc);
        set(11, lonFromRA(armc + arc / 3, eps));
        set(12, lonFromRA(armc + 2 * arc / 3, eps));
        set(2, lonFromRA(armc + arc + (180 - arc) / 3, eps));
        set(3, lonFromRA(armc + arc + 2 * (180 - arc) / 3, eps));
      }
    } else if (sys === "R" || sys === "C") {
      const divided = sys === "R" ? F.Meq : F.Z;
      // 中天沉到地平線下時，Swiss Ephemeris 把第十宮頭換成地平線上方子午圈的那一點
      // （天底），宮頭於是反向排列；本站拒收這種排列。示意圖照 Swiss 的定義畫。
      set(10, mcBelowHorizon(F) ? mc + 180 : mc); set(1, asc);
      for (const house of [11, 12, 2, 3]) {
        const a = ALPHA[house] * D;
        set(house, northSouthCircleCut(F, add(scale(divided, Math.cos(a)), scale(F.E, Math.sin(a)))));
      }
    } else if (sys === "P") {
      if (Math.abs(lat) >= 90 - eps) geometry = false;
      else {
        set(10, mc); set(1, asc);
        for (const house of [11, 12, 2, 3]) {
          const lon = placidusCusp(F, house);
          if (lon === null) { geometry = false; break; }
          set(house, lon);
        }
      }
    } else {
      throw new Error(`unknown house system ${sys}`);
    }
    return { geometry, cusps: geometry ? out : null, asc, mc, mcBelowHorizon: mcBelowHorizon(F), frame: F };
  }

  return Object.freeze({
    OBLIQUITY, D, SYSTEMS, QUADRANT, ALPHA, EASTERN_CUSPS,
    mod360, dot, cross, scale, add, sub, neg, norm,
    frame, eclVec, raDecVec, lonFromRA, decOfLon, lonOfVec, semiArc, ascOf, mcOf,
    placidusHourAngle, cusps, siteStatus,
  });
});
