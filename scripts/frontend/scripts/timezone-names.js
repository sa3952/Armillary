// 由 scripts/frontend/build_pages.py 依 backend/app/iana_zone_names.json 產生，不要手改。
// 服務接受的 IANA 時區名稱；手動輸入的時區在送出前以同一份名單檢查。
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.TimezoneNames = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  // [區域, 以空格分開的其餘部分]：依名單原順序展開（沒有區域的名稱如 UTC，區域是空字串）。
  const RUNS = [
    ["Africa", "Abidjan Accra Addis_Ababa Algiers Asmara Bamako Bangui Banjul Bissau Blantyre Brazzaville Bujumbura Cairo Casablanca Ceuta Conakry Dakar Dar_es_Salaam Djibouti Douala El_Aaiun Freetown Gaborone Harare Johannesburg Juba Kampala Khartoum Kigali Kinshasa Lagos Libreville Lome Luanda Lubumbashi Lusaka Malabo Maputo Maseru Mbabane Mogadishu Monrovia Nairobi Ndjamena Niamey Nouakchott Ouagadougou Porto-Novo Sao_Tome Timbuktu Tripoli Tunis Windhoek"],
    ["America", "Adak Anchorage Anguilla Antigua Araguaina Argentina/Buenos_Aires Argentina/Catamarca Argentina/Cordoba Argentina/Jujuy Argentina/La_Rioja Argentina/Mendoza Argentina/Rio_Gallegos Argentina/Salta Argentina/San_Juan Argentina/San_Luis Argentina/Tucuman Argentina/Ushuaia Aruba Asuncion Atikokan Atka Bahia Bahia_Banderas Barbados Belem Belize Blanc-Sablon Boa_Vista Bogota Boise Cambridge_Bay Campo_Grande Cancun Caracas Cayenne Cayman Chicago Chihuahua Ciudad_Juarez Coral_Harbour Costa_Rica Coyhaique Creston Cuiaba Curacao Danmarkshavn Dawson Dawson_Creek Denver Detroit Dominica Edmonton Eirunepe El_Salvador Ensenada Fort_Nelson Fortaleza Glace_Bay Goose_Bay Grand_Turk Grenada Guadeloupe Guatemala Guayaquil Guyana Halifax Havana Hermosillo Indiana/Indianapolis Indiana/Knox Indiana/Marengo Indiana/Petersburg Indiana/Tell_City Indiana/Vevay Indiana/Vincennes Indiana/Winamac Inuvik Iqaluit Jamaica Juneau Kentucky/Louisville Kentucky/Monticello Kralendijk La_Paz Lima Los_Angeles Lower_Princes Maceio Managua Manaus Marigot Martinique Matamoros Mazatlan Menominee Merida Metlakatla Mexico_City Miquelon Moncton Monterrey Montevideo Montreal Montserrat Nassau New_York Nipigon Nome Noronha North_Dakota/Beulah North_Dakota/Center North_Dakota/New_Salem Nuuk Ojinaga Panama Pangnirtung Paramaribo Phoenix Port-au-Prince Port_of_Spain Porto_Acre Porto_Velho Puerto_Rico Punta_Arenas Rainy_River Rankin_Inlet Recife Regina Resolute Rio_Branco Santa_Isabel Santarem Santiago Santo_Domingo Sao_Paulo Scoresbysund Shiprock Sitka St_Barthelemy St_Johns St_Kitts St_Lucia St_Thomas St_Vincent Swift_Current Tegucigalpa Thule Thunder_Bay Tijuana Toronto Tortola Vancouver Virgin Whitehorse Winnipeg Yakutat Yellowknife"],
    ["Antarctica", "Casey Davis DumontDUrville Macquarie Mawson McMurdo Palmer Rothera Syowa Troll Vostok"],
    ["Arctic", "Longyearbyen"],
    ["Asia", "Aden Almaty Amman Anadyr Aqtau Aqtobe Ashgabat Atyrau Baghdad Bahrain Baku Bangkok Barnaul Beirut Bishkek Brunei Chita Chongqing Colombo Damascus Dhaka Dili Dubai Dushanbe Famagusta Gaza Harbin Hebron Ho_Chi_Minh Hong_Kong Hovd Irkutsk Istanbul Jakarta Jayapura Jerusalem Kabul Kamchatka Karachi Kashgar Kathmandu Khandyga Kolkata Krasnoyarsk Kuala_Lumpur Kuching Kuwait Macau Magadan Makassar Manila Muscat Nicosia Novokuznetsk Novosibirsk Omsk Oral Phnom_Penh Pontianak Pyongyang Qatar Qostanay Qyzylorda Riyadh Sakhalin Samarkand Seoul Shanghai Singapore Srednekolymsk Taipei Tashkent Tbilisi Tehran Tel_Aviv Thimphu Tokyo Tomsk Ulaanbaatar Urumqi Ust-Nera Vientiane Vladivostok Yakutsk Yangon Yekaterinburg Yerevan"],
    ["Atlantic", "Azores Bermuda Canary Cape_Verde Faroe Jan_Mayen Madeira Reykjavik South_Georgia St_Helena Stanley"],
    ["Australia", "Adelaide Brisbane Broken_Hill Canberra Currie Darwin Eucla Hobart Lindeman Lord_Howe Melbourne Perth Sydney Yancowinna"],
    ["Etc", "GMT GMT+0 GMT+1 GMT+10 GMT+11 GMT+12 GMT+2 GMT+3 GMT+4 GMT+5 GMT+6 GMT+7 GMT+8 GMT+9 GMT-0 GMT-1 GMT-10 GMT-11 GMT-12 GMT-13 GMT-14 GMT-2 GMT-3 GMT-4 GMT-5 GMT-6 GMT-7 GMT-8 GMT-9 GMT0 Greenwich UCT UTC Universal Zulu"],
    ["Europe", "Amsterdam Andorra Astrakhan Athens Belfast Belgrade Berlin Bratislava Brussels Bucharest Budapest Busingen Chisinau Copenhagen Dublin Gibraltar Guernsey Helsinki Isle_of_Man Istanbul Jersey Kaliningrad Kirov Kyiv Lisbon Ljubljana London Luxembourg Madrid Malta Mariehamn Minsk Monaco Moscow Nicosia Oslo Paris Podgorica Prague Riga Rome Samara San_Marino Sarajevo Saratov Simferopol Skopje Sofia Stockholm Tallinn Tirane Tiraspol Ulyanovsk Vaduz Vatican Vienna Vilnius Volgograd Warsaw Zagreb Zurich"],
    ["", "GMT"],
    ["Indian", "Antananarivo Chagos Christmas Cocos Comoro Kerguelen Mahe Maldives Mauritius Mayotte Reunion"],
    ["Pacific", "Apia Auckland Bougainville Chatham Chuuk Easter Efate Fakaofo Fiji Funafuti Galapagos Gambier Guadalcanal Guam Honolulu Johnston Kanton Kiritimati Kosrae Kwajalein Majuro Marquesas Midway Nauru Niue Norfolk Noumea Pago_Pago Palau Pitcairn Pohnpei Port_Moresby Rarotonga Saipan Samoa Tahiti Tarawa Tongatapu Wake Wallis Yap"],
    ["", "UTC"],
  ];
  const NAMES = new Set(RUNS.flatMap(([area, rest]) => rest.split(" ").map((name) => (area ? `${area}/${name}` : name))));
  return Object.freeze({
    accepts: (name) => NAMES.has(name),
    size: NAMES.size,
  });
});
