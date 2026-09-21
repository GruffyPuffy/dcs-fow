# Curated forces, aircraft and DCS-owned logistics

The spawn menu includes additional curated ground groups per side: a combined-arms fighting force, mechanized infantry, supported tank platoon, infantry section, escorted supply convoy, escorted fuel convoy, and mobile short-range air defense. The viewer shows each group's composition. Infantry are currently dismounted; embarkation is not implemented.

Aircraft presets cover 21 types: Blue Hornet, Eagle, Viper, Tomcat, Warthog, Harrier, Hercules, Globemaster, Sentry and two Stratotanker variants; Red MiG-29, Su-27, Su-33, MiG-31, Su-25T, Su-24M, IL-76, An-26, A-50 and IL-78. CAP and CAS payload stations are checked against the pinned pydcs definitions. Transport, tanker and AWACS behavior still needs live DCS validation.

## State ownership

DCS is authoritative for units, positions, damage, fuel, weapons, warehouse inventory, cargo, airbase ownership and mission outcomes. FoW observes and filters that state, then submits validated commands through the generic bridge. SQLite may retain observations, order history and viewer-only labels, but it must not create a parallel inventory or battlefield state.

Logistics should therefore build on DCS warehouses and Dynamic Cargo. The next investigation is to configure Batumi and Gudauta warehouse stocks in the generated mission, observe their runtime inventory through the DCS scripting API, and determine which native cargo actions work for AI and player transports. Only gaps that DCS cannot represent should become FoW rules, and those rules should resolve back into visible DCS state whenever possible.

The curated supply and fuel convoys currently spawn real DCS vehicles, but FoW assigns them no invented cargo balance. Their logistics effect remains undefined until it can be tied to DCS warehouse or cargo state. They can still be moved, defended and destroyed like other DCS groups.

## Strategic base trial

Batumi and Gudauta are the Blue and Red home bases. Other Caucasus airbases remain neutral in DCS. Kobuleti, Senaki-Kolkhi, Kutaisi and Sukhumi-Babushara are configured as the first attackable objectives. The bridge reports every airbase's live DCS coalition; FoW does not maintain ownership separately.

**Attack base** randomly selects a curated combined-arms package, spawns it at a configured approach about 5 km from the objective, and gives it a DCS route into the native capture area. Each coalition may have two active assaults. **Defend base** randomly places one approved defense package at a base DCS currently reports as owned. A commander may also choose and place an approved defense package within 8 km of an owned strategic base. Each base may have three active spawned defense packages. Dynamically spawned assault and defense forces are capped at 80 ground units per coalition; all active aircraft are capped at 12 per coalition.

The first trial is deliberately ground-only. DCS decides combat and airbase capture. FoW does not delete defenders, force ownership changes, or declare victory. Automatic CAP, CAS and SEAD support can be added after native capture and the configured ground approaches work in a live mission.

## Live trial

Build and deploy the updated mission, then reload it in DCS; the generic status bridge now reports native airbase ownership. Restart the FoW server and refresh the viewer. Launch an assault on Kobuleti, observe the approach, and verify that DCS changes its coalition when surviving ground forces enter the capture area. Try opposing assaults and player intervention before adding air support.

For aircraft catalog changes, run `./scripts/build-air-catalog.sh` to regenerate server-owned templates using the project's pinned pydcs 0.15.0 environment. This does not require a mission rebuild. Ground catalog changes are read directly by the FoW server.

References: the [DCS User Manual](https://www.digitalcombatsimulator.com/upload/iblock/ed6/87v22jwd1xh51i3rgki944xsf503istq/DCS_User_Manual_EN_2020.pdf), [DCS Dynamic Cargo development notes](https://www.digitalcombatsimulator.com/en/news/2024-08-23/), upstream [pydcs examples](https://github.com/pydcs/dcs), and [pydcs task definitions](https://github.com/pydcs/dcs/blob/master/dcs/task.py).
