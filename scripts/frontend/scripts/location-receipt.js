(function attachLocationReceipt(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.LocationReceipt = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildLocationReceipt() {
  "use strict";

  // 服務只在座標與目錄列的儲存值（IEEE-754 binary64）完全相同時接受目錄地點，所以這裡也比數值本身：「22.9915000000」與
  // 22.9915 相同，差一個可表示的倍精度數就不同，改送手動座標，而不是帶著目錄記錄 id 送出另一組座標。
  function sameCoordinate(currentValue, selectedValue) {
    const current = Number(currentValue);
    const selected = Number(selectedValue);
    return Number.isFinite(current) && Number.isFinite(selected) && current === selected;
  }

  function manualLocation(latitude, longitude, altitudeM) {
    return {
      latitude: Number(latitude), longitude: Number(longitude), altitude_m: Number(altitudeM),
      location_source: "manual", location_precision: "user_supplied_coordinates",
    };
  }

  function buildLocationInput({ latitude, longitude, altitudeM, selectedPlace }) {
    const manual = manualLocation(latitude, longitude, altitudeM);
    if (!selectedPlace) return manual;
    const traceable = typeof selectedPlace.source === "string" && selectedPlace.source.length > 0
      && typeof selectedPlace.source_record_id === "string" && selectedPlace.source_record_id.length > 0
      && typeof selectedPlace.location_precision === "string" && selectedPlace.location_precision.length > 0;
    const unchanged = sameCoordinate(latitude, selectedPlace.latitude) && sameCoordinate(longitude, selectedPlace.longitude);
    if (!traceable || !unchanged) return manual;
    return {
      latitude: manual.latitude, longitude: manual.longitude, altitude_m: manual.altitude_m,
      place_label: selectedPlace.display_name || selectedPlace.name, location_source: selectedPlace.source,
      source_record_id: selectedPlace.source_record_id, location_precision: selectedPlace.location_precision,
    };
  }

  return Object.freeze({ buildLocationInput, sameCoordinate });
});
