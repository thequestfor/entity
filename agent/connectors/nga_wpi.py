"""Official NGA World Port Index reference connector."""

import io
import struct
import urllib.request
import zipfile

from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.source_registry import validate_connector_url
from agent.intelligence.store import utc_now


WPI_DOWNLOAD_URL = (
    "https://msi.nga.mil/api/publications/download?"
    "key=16694622/SFH00000/WPI_Shapefile.zip&type=view"
)
SELECTED_FIELDS = {
    "INDEX_NO", "PORT_NAME", "COUNTRY", "LATITUDE", "LONGITUDE",
    "HARBORSIZE", "HARBORTYPE", "SHELTER", "CHAN_DEPTH", "ANCH_DEPTH",
    "CARGODEPTH", "OIL_DEPTH", "MAX_VESSEL", "PORTOFENTR", "PILOT_REQD",
    "PILOTAVAIL", "TUG_ASSIST", "COMM_RAIL", "CARGOWHARF", "CARGO_ANCH",
    "MED_FACIL", "CRANEFIXED", "CRANEMOBIL", "PROVISIONS", "WATER",
    "FUEL_OIL", "DIESEL", "REPAIRCODE", "DRYDOCK", "RAILWAY",
}


class NgaWorldPortIndexConnector:
    source_id = "nga_world_port_index"
    name = "NGA World Port Index"
    kind = "infrastructure_reference"
    base_url = WPI_DOWNLOAD_URL
    credibility = 0.94
    poll_seconds = 604800

    def __init__(
        self,
        timeout=30,
        max_items=5000,
        max_bytes=5_000_000,
        max_uncompressed_bytes=60_000_000,
        poll_seconds=604800,
        fetch_archive=None,
        enabled=True,
    ):
        self.timeout = max(1, int(timeout))
        self.max_items = max(1, min(10000, int(max_items)))
        self.max_bytes = max(1000, min(20_000_000, int(max_bytes)))
        self.max_uncompressed_bytes = max(
            1000, min(100_000_000, int(max_uncompressed_bytes))
        )
        self.poll_seconds = max(86400, int(poll_seconds))
        self._fetch_archive_override = fetch_archive
        self.enabled = bool(enabled)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        archive = self._fetch_archive()
        rows = _read_wpi_dbf(
            archive,
            max_records=self.max_items,
            max_uncompressed_bytes=self.max_uncompressed_bytes,
        )
        items = []
        for row in rows:
            latitude = _coordinate(row.get("LATITUDE"), -90, 90)
            longitude = _coordinate(row.get("LONGITUDE"), -180, 180)
            external_id = _identifier(row.get("INDEX_NO"))
            name = str(row.get("PORT_NAME") or "").strip()
            if not external_id or not name or latitude is None or longitude is None:
                continue
            country_code = str(row.get("COUNTRY") or "").strip().upper()[:3]
            properties = {
                key.lower(): value
                for key, value in row.items()
                if key not in {"INDEX_NO", "PORT_NAME", "COUNTRY", "LATITUDE", "LONGITUDE"}
                and value not in (None, "", "0.000000")
            }
            items.append(SourceItem(
                external_id=external_id,
                title=name,
                url=f"https://msi.nga.mil/Publications/WPI?port={external_id}",
                summary=(
                    f"The NGA World Port Index lists {name} in {country_code or 'an unspecified country'}. "
                    "This reference entry does not establish current operating status."
                ),
                category="infrastructure-port",
                latitude=latitude,
                longitude=longitude,
                metadata={
                    "epistemic_type": "reference",
                    "asset_type": "port",
                    "name": name,
                    "country_code": country_code,
                    "identifiers": {"wpi_index_number": external_id},
                    "properties": properties,
                    "geometry": {
                        "type": "Point",
                        "coordinates": [longitude, latitude],
                    },
                },
            ))
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "edition": "2019",
            "asset_count": len(items),
        })

    def _fetch_archive(self):
        url = validate_connector_url(self, self.base_url)
        if self._fetch_archive_override is not None:
            payload = bytes(self._fetch_archive_override(url))
            if len(payload) > self.max_bytes:
                raise ValueError("NGA WPI response exceeded configured byte limit")
            return payload
        request = urllib.request.Request(url, headers={
            "Accept": "application/zip, application/octet-stream",
            "User-Agent": "EntityIntelligence/0.1 (read-only reference collector)",
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = response.read(self.max_bytes + 1)
        if len(payload) > self.max_bytes:
            raise ValueError("NGA WPI response exceeded configured byte limit")
        return payload


def _read_wpi_dbf(archive, max_records, max_uncompressed_bytes):
    try:
        bundle = zipfile.ZipFile(io.BytesIO(archive))
        with bundle:
            candidates = [
                item for item in bundle.infolist()
                if item.filename.lower().endswith(".dbf")
            ]
            if len(candidates) != 1:
                raise ValueError("NGA WPI archive must contain exactly one DBF file")
            member = candidates[0]
            if member.file_size > max_uncompressed_bytes:
                raise ValueError("NGA WPI DBF exceeded configured uncompressed byte limit")
            with bundle.open(member) as stream:
                return _read_dbf_stream(stream, max_records)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("NGA WPI response was not a valid ZIP archive") from exc


def _read_dbf_stream(stream, max_records):
    header = stream.read(32)
    if len(header) != 32:
        raise ValueError("NGA WPI DBF header was truncated")
    record_count = struct.unpack("<I", header[4:8])[0]
    header_length = struct.unpack("<H", header[8:10])[0]
    record_length = struct.unpack("<H", header[10:12])[0]
    if record_count > 100_000 or header_length > 16_384 or record_length > 32_768:
        raise ValueError("NGA WPI DBF declared unsafe dimensions")
    descriptors = stream.read(header_length - 32)
    fields = _dbf_fields(descriptors)
    rows = []
    for _ in range(min(record_count, max_records)):
        record = stream.read(record_length)
        if len(record) != record_length:
            break
        if record[:1] == b"*":
            continue
        row = {}
        for name, start, length in fields:
            if name not in SELECTED_FIELDS:
                continue
            row[name] = record[start:start + length].decode(
                "latin-1", errors="replace"
            ).strip()
        rows.append(row)
    return rows


def _dbf_fields(descriptors):
    fields = []
    position = 1
    for offset in range(0, len(descriptors), 32):
        descriptor = descriptors[offset:offset + 32]
        if not descriptor or descriptor[0] == 0x0D or len(descriptor) < 32:
            break
        name = descriptor[:11].split(b"\0", 1)[0].decode("ascii", errors="ignore")
        length = int(descriptor[16])
        fields.append((name, position, length))
        position += length
    return fields


def _identifier(value):
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return ""


def _coordinate(value, minimum, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if minimum <= number <= maximum else None
