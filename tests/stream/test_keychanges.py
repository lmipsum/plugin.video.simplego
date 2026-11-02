from resources.lib.stream import keychanges


def group(kind, starts, scale=10, duration=10):
    aset = '<AdaptationSet contentType="%s">' % kind
    return keychanges.Group(aset, '<Representation id="%s"/>' % kind, scale, [(s, duration) for s in starts])


def keyed(changes):
    """key(group, n) for tracks whose key changes at the given segment indexes (per track kind)."""
    asked = []

    def key(g, n):
        asked.append((g.tag, n))
        kind = "video" if "video" in g.aset else "audio"
        part = sum(1 for i in changes[kind] if n >= i)
        return "pssh-%d" % part, "kid-%s-%d" % (kind, part)

    return key, asked


def test_a_single_key_change_is_found_in_every_track():
    video, audio = group("video", range(0, 400, 10)), group("audio", range(-2, 398, 10))
    key, asked = keyed({"video": [23], "audio": [23]})
    assert keychanges.find([video, audio], key) == [[23], [23]]
    # The video by binary search, the audio only around the change.
    assert len([a for a in asked if "audio" in a[0]]) == 2


def test_several_key_changes_in_a_row_are_all_found():
    video = group("video", range(0, 1000, 10))
    key, _ = keyed({"video": [17, 60, 81], "audio": []})
    assert keychanges.find([video], key) == [[17, 60, 81]]


def test_a_track_whose_key_never_changes_needs_only_its_first_and_last_fragment():
    video = group("video", range(0, 400, 10))
    key, asked = keyed({"video": [], "audio": []})
    assert keychanges.find([video], key) == [[]]
    assert sorted(n for _, n in asked) == [0, 39]


def test_an_audio_track_changing_elsewhere_than_the_video_is_searched_on_its_own():
    video, audio = group("video", range(0, 400, 10)), group("audio", range(0, 400, 10))
    key, _ = keyed({"video": [23], "audio": [30]})
    assert keychanges.find([video, audio], key) == [[23], [30]]


def test_changes_found_before_are_taken_as_they_are():
    video = group("video", range(0, 400, 10))

    def key(g, n):
        raise AssertionError("no fragment should be read")

    assert keychanges.find([video], key, hint=[[23]]) == [[23]]


def test_a_hint_that_does_not_fit_the_timeline_is_not_taken():
    video = group("video", range(0, 100, 10))
    key, _ = keyed({"video": [4], "audio": []})
    assert keychanges.find([video], key, hint=[[23]]) == [[4]]


def test_the_groups_of_a_manifest_are_its_encrypted_tracks_with_timelines():
    from resources.lib.stream import dash

    aset = (
        '<AdaptationSet contentType="video"><ContentProtection schemeIdUri="%s" value="Widevine"/>'
        '<SegmentTemplate timescale="10" media="v/$Time$" initialization="v/Init"><SegmentTimeline>'
        '<S t="100" d="10" r="2"/></SegmentTimeline></SegmentTemplate>'
        '<Representation id="hd" bandwidth="3500000"/><Representation id="sd" bandwidth="1500000"/></AdaptationSet>'
    ) % dash.WIDEVINE_URN
    plain = '<AdaptationSet contentType="text"><Representation id="s" bandwidth="1"/></AdaptationSet>'
    (found,) = keychanges.groups([aset, plain], "https://cdn.example/x/Manifest")
    assert found.scale == 10 and found.segments == [(100, 10), (110, 10), (120, 10)]
    assert 'id="sd"' in found.tag  # the smallest quality is read: all share one key
