"""Coalition AWACS contact memory; never update from the omniscient roster."""
import math
import uuid


class ContactPicture:
    retention_seconds = 300

    def __init__(self):
        self.mission_id = None
        self.time = -1
        self.contacts = {}

    def update(self, snapshot):
        now = float(snapshot['time'])
        mission_id = snapshot.get('mission_id', 'legacy-status')
        if mission_id != self.mission_id or now < self.time - 5:
            self.contacts.clear()
        self.mission_id, self.time = mission_id, now
        for contact in self.contacts.values():
            contact['current'] = False
        for report in snapshot.get('awacs_reports', []):
            if report.get('side') not in (1, 2):
                continue
            if not all(isinstance(report.get(k), (int, float)) and math.isfinite(report[k])
                       for k in ('lat', 'lon', 'altitude_m')):
                continue
            key = (report['side'], report['target_id'])
            previous = self.contacts.get(key, {})
            if previous.get('destroyed'):
                continue
            sources = set(previous.get('sources', [])) if previous.get('current') else set()
            sources.add(report['source'])
            self.contacts[key] = {
                'id': previous.get('id', uuid.uuid4().hex[:12]),
                'side': report['side'], 'lat': report['lat'], 'lon': report['lon'],
                'altitude_m': report['altitude_m'], 'type': report.get('type') or previous.get('type'),
                'sources': sorted(sources), 'method': 'radar', 'last_seen': now, 'current': True,
            }
        for event in snapshot.get('kill_reports', []):
            # Only the credited coalition gets confirmation. Do not reveal
            # unrelated deaths to observers who merely lost radar contact.
            contact = self.contacts.get((event.get('side'), event.get('target_id')))
            if contact and event.get('target_side') in (1, 2) and event['target_side'] != event['side']:
                event['contact_id'] = contact['id']
                contact.update(destroyed=True, current=False, destroyed_at=event['time'])
        self.contacts = {key: value for key, value in self.contacts.items()
                         if (now - value['destroyed_at'] <= 60 if value.get('destroyed')
                             else now - value['last_seen'] <= self.retention_seconds)}
        return [dict(value, age_seconds=max(0, now - value['last_seen']))
                for value in self.contacts.values()]
