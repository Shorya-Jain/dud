from dud import ids

UUID = "GPU-5e1a7c3d-90b2-4f61-8c3e-a1b2c3d4e500"


def test_hash_scheme_is_frozen():
    # If this test fails, the card IDs of all earlier readings no longer match.
    # Do not change the expected values. Add a new hash scheme instead.
    assert ids.uuid_hash(UUID) == "0e8d2a6cdfb6b9dd85e4e9009e7cce44cadfbd631a1ed947431f0318ec62ba99"
    assert ids.serial_hash("1652922001000") == "b889356b92003353f78b0ecb6e683b3f4915850fbfbc7407ba511f737f7d0c4f"


def test_hash_normalizes_case_and_space():
    assert ids.uuid_hash(f"  {UUID.upper()} \n") == ids.uuid_hash(UUID)
    assert ids.serial_hash(" 1652922001000") == ids.serial_hash("1652922001000")


def test_uuid_and_serial_hashes_differ_for_same_text():
    assert ids.uuid_hash("123") != ids.serial_hash("123")


def test_real_id_detection():
    assert ids.is_real_id(UUID)
    for value in (None, "", "N/A", "[N/A]", "0", ids.marker("uuid", "ab" * 32)):
        assert not ids.is_real_id(value)


XML = f"""<nvidia_smi_log>
<gpu id="00000000:18:00.0">
<serial>1652922001000</serial>
<uuid>{UUID}</uuid>
<chassis_serial_number>CH123</chassis_serial_number>
<board_serial>N/A</board_serial>
<processes>
<process_info><pid>1</pid><process_name>secret_job.py</process_name></process_info>
</processes>
<accounted_processes>
</accounted_processes>
</gpu>
</nvidia_smi_log>"""


def test_redact_removes_ids_and_processes():
    text, done = ids.redact_smi_xml(XML)
    assert UUID not in text
    assert "1652922001000" not in text
    assert "CH123" not in text
    assert "secret_job.py" not in text
    assert ids.uuid_hash(UUID) in text
    assert "<board_serial>N/A</board_serial>" in text
    assert "<accounted_processes>\n</accounted_processes>" in text  # Empty lists stay as they are.
    assert done == ["chassis_serial_number", "processes", "serial", "uuid"]


def test_redact_is_idempotent():
    once, _ = ids.redact_smi_xml(XML)
    twice, done = ids.redact_smi_xml(once)
    assert once == twice
    assert done == []


def test_marker_round_trip():
    h = ids.uuid_hash(UUID)
    assert ids.hash_from_marker(ids.marker("uuid", h)) == h
