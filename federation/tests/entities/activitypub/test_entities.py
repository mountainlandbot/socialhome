from unittest.mock import patch

from Crypto.PublicKey.RSA import RsaKey

from federation.entities.activitypub.constants import (
    CONTEXTS_DEFAULT, CONTEXT_MANUALLY_APPROVES_FOLLOWERS, CONTEXT_LD_SIGNATURES)
from federation.entities.activitypub.entities import ActivitypubAccept
from federation.tests.fixtures.keys import PUBKEY
from federation.types import UserType


class TestEntitiesConvertToAS2:
    def test_accept_to_as2(self, activitypubaccept):
        result = activitypubaccept.to_as2()
        assert result == {
            "@context": CONTEXTS_DEFAULT,
            "id": "https://localhost/accept",
            "type": "Accept",
            "actor": "https://localhost/profile",
            "object": {
                "@context": CONTEXTS_DEFAULT,
                "id": "https://localhost/follow",
                "type": "Follow",
                "actor": "https://localhost/profile",
                "object": "https://example.com/profile",
            },
        }

    def test_comment_to_as2(self, activitypubcomment):
        result = activitypubcomment.to_as2()
        assert result == {
            '@context': [
                'https://www.w3.org/ns/activitystreams',
                {'Hashtag': 'as:Hashtag'},
                'https://w3id.org/security/v1',
                {'sensitive': 'as:sensitive'},
            ],
            'type': 'Create',
            'id': 'http://127.0.0.1:8000/post/123456/#create',
            'actor': 'http://127.0.0.1:8000/profile/123456/',
            'object': {
                'id': 'http://127.0.0.1:8000/post/123456/',
                'type': 'Note',
                'attributedTo': 'http://127.0.0.1:8000/profile/123456/',
                'content': 'raw_content',
                'published': '2019-04-27T00:00:00',
                'inReplyTo': 'http://127.0.0.1:8000/post/012345/',
                'sensitive': False,
                'summary': None,
                'tag': [],
                'url': '',
            },
            'published': '2019-04-27T00:00:00',
        }

    def test_follow_to_as2(self, activitypubfollow):
        result = activitypubfollow.to_as2()
        assert result == {
            "@context": CONTEXTS_DEFAULT,
            "id": "https://localhost/follow",
            "type": "Follow",
            "actor": "https://localhost/profile",
            "object": "https://example.com/profile"
        }

    def test_follow_to_as2__undo(self, activitypubundofollow):
        result = activitypubundofollow.to_as2()
        result["object"]["id"] = "https://localhost/follow"  # Real object will have a random UUID postfix here
        assert result == {
            "@context": CONTEXTS_DEFAULT,
            "id": "https://localhost/undo",
            "type": "Undo",
            "actor": "https://localhost/profile",
            "object": {
                "id": "https://localhost/follow",
                "type": "Follow",
                "actor": "https://localhost/profile",
                "object": "https://example.com/profile",
            }
        }

    def test_post_to_as2(self, activitypubpost):
        result = activitypubpost.to_as2()
        assert result == {
            '@context': [
                'https://www.w3.org/ns/activitystreams',
                {'Hashtag': 'as:Hashtag'},
                'https://w3id.org/security/v1',
                {'sensitive': 'as:sensitive'},
            ],
            'type': 'Create',
            'id': 'http://127.0.0.1:8000/post/123456/#create',
            'actor': 'http://127.0.0.1:8000/profile/123456/',
            'object': {
                'id': 'http://127.0.0.1:8000/post/123456/',
                'type': 'Note',
                'attributedTo': 'http://127.0.0.1:8000/profile/123456/',
                'content': 'raw_content',
                'published': '2019-04-27T00:00:00',
                'inReplyTo': None,
                'sensitive': False,
                'summary': None,
                'tag': [],
                'url': '',
            },
            'published': '2019-04-27T00:00:00',
        }

    @patch("federation.entities.activitypub.objects.fetch_content_type", return_value="image/jpeg")
    def test_profile_to_as2(self, mock_fetch, activitypubprofile):
        result = activitypubprofile.to_as2()
        assert result == {
            "@context": CONTEXTS_DEFAULT + [
                CONTEXT_LD_SIGNATURES,
                CONTEXT_MANUALLY_APPROVES_FOLLOWERS,
            ],
            "endpoints": {
                "sharedInbox": "https://example.com/public",
            },
            "followers": "https://example.com/bob/followers/",
            "following": "https://example.com/bob/following/",
            "id": "https://example.com/bob",
            "inbox": "https://example.com/bob/private",
            "manuallyApprovesFollowers": False,
            "name": "Bob Bobertson",
            "outbox": "https://example.com/bob/outbox/",
            "publicKey": {
                "id": "https://example.com/bob#main-key",
                "owner": "https://example.com/bob",
                "publicKeyPem": PUBKEY,
            },
            "type": "Person",
            "url": "https://example.com/bob-bobertson",
            "summary": "foobar",
            "icon": {
                "type": "Image",
                "url": "urllarge",
                "mediaType": "image/jpeg",
            }
        }


class TestEntitiesPostReceive:
    @patch("federation.utils.activitypub.retrieve_and_parse_profile", autospec=True)
    @patch("federation.entities.activitypub.entities.handle_send", autospec=True)
    def test_follow_post_receive__sends_correct_accept_back(
            self, mock_send, mock_retrieve, activitypubfollow, profile
    ):
        mock_retrieve.return_value = profile
        activitypubfollow.post_receive()
        args, kwargs = mock_send.call_args_list[0]
        assert isinstance(args[0], ActivitypubAccept)
        assert args[0].activity_id.startswith("https://example.com/profile#accept-")
        assert args[0].actor_id == "https://example.com/profile"
        assert args[0].target_id == "https://localhost/follow"
        assert isinstance(args[1], UserType)
        assert args[1].id == "https://example.com/profile"
        assert isinstance(args[1].private_key, RsaKey)
        assert kwargs['recipients'] == [{
            "endpoint": "https://example.com/bob/private",
            "fid": "https://localhost/profile",
            "protocol": "activitypub",
            "public": False,
        }]