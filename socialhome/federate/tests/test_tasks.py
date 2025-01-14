from unittest.mock import patch, ANY

from django.test import override_settings
from federation.entities.base import Comment, Post
from federation.tests.fixtures.keys import get_dummy_private_key
from test_plus import TestCase

from socialhome.content.tests.factories import (
    ContentFactory, LocalContentFactory, PublicContentFactory, LimitedContentFactory)
from socialhome.enums import Visibility
from socialhome.federate.tasks import (
    receive_task, send_content, send_content_retraction, send_reply, forward_entity, _get_remote_followers,
    send_follow_change, send_profile, send_share, send_profile_retraction, _get_limited_recipients)
from socialhome.tests.utils import SocialhomeTestCase
from socialhome.users.models import Profile
from socialhome.users.tests.factories import (
    UserFactory, ProfileFactory, PublicUserFactory, PublicProfileFactory, UserWithKeyFactory, LimitedUserFactory,
    SelfUserFactory)


@patch("socialhome.federate.tasks.process_entities", autospec=True)
class TestReceiveTask(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = UserFactory()

    @patch("socialhome.federate.tasks.handle_receive", return_value=("sender", "diaspora", ["entity"]), autospec=True)
    def test_receive_task_runs(self, mock_handle_receive, mock_process_entities):
        receive_task("foobar")
        mock_process_entities.assert_called_with(["entity"])

    @patch("socialhome.federate.tasks.handle_receive", return_value=("sender", "diaspora", []), autospec=True)
    def test_receive_task_returns_none_on_no_entities(self, mock_handle_receive, mock_process_entities):
        self.assertIsNone(receive_task("foobar"))
        self.assertTrue(mock_process_entities.called is False)

    @patch("socialhome.federate.tasks.handle_receive", return_value=("sender", "diaspora", ["entity"]), autospec=True)
    def test_receive_task_with_uuid(self, mock_handle_receive, mock_process_entities):
        receive_task("foobar", uuid=self.user.profile.uuid)
        mock_process_entities.assert_called_with(["entity"])


class TestSendContent(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = UserFactory()
        cls.profile = cls.user.profile
        cls.remote_profile = ProfileFactory(with_key=True)
        cls.create_content_set(author=cls.profile)

    @patch("socialhome.federate.tasks.make_federable_content", return_value=None, autospec=True)
    def test_only_limited_and_public_content_calls_make_federable_content(self, mock_maker):
        send_content(self.self_content.id, "foo")
        self.assertTrue(mock_maker.called is False)
        send_content(self.site_content.id, "foo")
        self.assertTrue(mock_maker.called is False)
        send_content(self.limited_content.id, self.limited_content.activities.first().fid)
        mock_maker.assert_called_once_with(self.limited_content)
        mock_maker.reset_mock()
        send_content(self.public_content.id, self.public_content.activities.first().fid)
        mock_maker.assert_called_once_with(self.public_content)

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.make_federable_content")
    def test_handle_send_is_called(self, mock_maker, mock_send):
        post = Post()
        mock_maker.return_value = post
        send_content(self.public_content.id, self.public_content.activities.first().fid)
        mock_send.assert_called_once_with(
            post,
            self.public_content.author.federable,
            [
                {'endpoint': 'https://matrix.127.0.0.1:8000', 'fid': self.public_content.author.mxid, 'public': True,
                 'protocol': 'matrix'},
            ],
            payload_logger=None,
        )

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.make_federable_content")
    def test_handle_send_is_called__limited_content(self, mock_maker, mock_send):
        post = Post()
        mock_maker.return_value = post
        send_content(
            self.limited_content.id,
            self.limited_content.activities.first().fid,
            recipient_id=self.remote_profile.id,
        )
        mock_send.assert_called_once_with(
            post,
            self.limited_content.author.federable,
            [self.remote_profile.get_recipient_for_visibility(Visibility.LIMITED)],
            payload_logger=None,
        )

    @patch("socialhome.federate.tasks.make_federable_content", return_value=None)
    @patch("socialhome.federate.tasks.logger.warning")
    def test_warning_is_logged_on_no_entity(self, mock_logger, mock_maker):
        send_content(self.public_content.id, "foo")
        self.assertTrue(mock_logger.called)

    @override_settings(DEBUG=True)
    @patch("socialhome.federate.tasks.handle_send")
    def test_content_not_sent_in_debug_mode(self, mock_send):
        send_content(self.public_content.id, "foo")
        self.assertTrue(mock_send.called is False)


class TestSendContentRetraction(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        author = UserFactory()
        cls.create_content_set(author=author.profile)
        cls.user = UserWithKeyFactory()
        cls.profile = cls.user.profile
        cls.limited_content2 = LimitedContentFactory(author=cls.profile)

    @patch("socialhome.federate.tasks.django_rq.enqueue", autospec=True)
    @patch("socialhome.federate.tasks._get_limited_recipients", autospec=True)
    @patch("socialhome.federate.tasks.make_federable_retraction", return_value="entity", autospec=True)
    def test_limited_retraction_calls_get_recipients(self, mock_maker, mock_get, mock_enqueue):
        send_content_retraction(self.limited_content2, self.limited_content2.author.id)
        self.assertTrue(mock_enqueue.called is True)
        self.assertTrue(mock_get.called is True)

    @patch("socialhome.federate.tasks.make_federable_retraction", return_value=None, autospec=True)
    def test_only_limited_and_public_content_calls_make_federable_retraction(self, mock_maker):
        send_content_retraction(self.self_content, self.self_content.author_id)
        self.assertTrue(mock_maker.called is False)
        send_content_retraction(self.site_content, self.site_content.author_id)
        self.assertTrue(mock_maker.called is False)
        send_content_retraction(self.limited_content, self.limited_content.author_id)
        mock_maker.assert_called_once_with(self.limited_content, self.limited_content.author)
        mock_maker.reset_mock()
        send_content_retraction(self.public_content, self.public_content.author_id)
        mock_maker.assert_called_once_with(self.public_content, self.public_content.author)

    @patch("socialhome.federate.tasks.django_rq.enqueue", autospec=True)
    @patch("socialhome.federate.tasks.make_federable_retraction", return_value="entity", autospec=True)
    def test_handle_create_payload_is_called(self, mock_maker, mock_enqueue):
        send_content_retraction(self.public_content, self.public_content.author_id)
        mock_enqueue.assert_called_once_with(
            ANY,
            "entity",
            self.public_content.author.federable,
            [],
            payload_logger=None,
            job_timeout=10000,
        )

    @patch("socialhome.federate.tasks.make_federable_retraction", return_value=None)
    @patch("socialhome.federate.tasks.logger.warning")
    def test_warning_is_logged_on_no_entity(self, mock_logger, mock_maker):
        send_content_retraction(self.public_content, self.public_content.author_id)
        self.assertTrue(mock_logger.called is True)

    @override_settings(DEBUG=True)
    @patch("socialhome.federate.tasks.handle_send")
    def test_content_not_sent_in_debug_mode(self, mock_send):
        send_content_retraction(self.public_content, self.public_content.author_id)
        self.assertTrue(mock_send.called is False)


@patch("socialhome.federate.tasks.handle_send")
@patch("socialhome.federate.tasks.make_federable_retraction", return_value="entity")
class TestSendProfileRetraction(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.public_user = PublicUserFactory()
        cls.public_profile = cls.public_user.profile
        cls.remote_profile = PublicProfileFactory()
        cls.user = SelfUserFactory()
        cls.profile = cls.user.profile
        cls.limited_user = LimitedUserFactory()
        cls.limited_profile = cls.limited_user.profile
        cls.public_profile.followers.add(cls.remote_profile)
        cls.limited_profile.followers.add(cls.remote_profile)

    @patch("socialhome.federate.tasks._get_remote_followers", autospec=True)
    def test_get_remote_followers_is_called(self, mock_followers, mock_make, mock_send):
        send_profile_retraction(self.public_profile)
        mock_followers.assert_called_once_with(self.public_profile, Visibility.PUBLIC)

    def test_handle_send_is_called(self, mock_make, mock_send):
        send_profile_retraction(self.public_profile)
        mock_send.assert_called_once_with(
            "entity",
            self.public_profile.federable,
            [
                self.remote_profile.get_recipient_for_visibility(Visibility.PUBLIC),
            ],
            payload_logger=None,
        )

    def test_non_local_profile_does_not_get_sent(self, mock_make, mock_send):
        send_profile_retraction(self.remote_profile)
        self.assertTrue(mock_send.called is False)

    def test_non_public_or_limited_profile_does_not_get_sent(self, mock_make, mock_send):
        send_profile_retraction(self.profile)
        self.assertTrue(mock_send.called is False)


class TestSendReply(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        author = UserFactory()
        private_key = get_dummy_private_key().exportKey().decode("utf-8")
        Profile.objects.filter(id=author.profile.id).update(rsa_private_key=private_key)
        author.profile.refresh_from_db()
        cls.public_content = ContentFactory(author=author.profile, visibility=Visibility.PUBLIC)
        cls.remote_content = ContentFactory(visibility=Visibility.PUBLIC)
        cls.remote_profile = ProfileFactory(with_key=True)
        cls.remote_reply = ContentFactory(parent=cls.public_content, author=cls.remote_profile)
        cls.reply = ContentFactory(parent=cls.public_content, author=author.profile)
        cls.reply2 = ContentFactory(parent=cls.remote_content, author=author.profile)
        cls.limited_content = LimitedContentFactory(author=cls.remote_profile)
        cls.limited_local_content = LimitedContentFactory(author=author.profile)
        cls.limited_reply = LimitedContentFactory(author=author.profile, parent=cls.limited_content)
        cls.limited_local_reply = LimitedContentFactory(author=author.profile, parent=cls.limited_local_content)
        cls.limited_local_reply.limited_visibilities.add(cls.remote_profile)

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.forward_entity")
    @patch("socialhome.federate.tasks.make_federable_content")
    def test_send_reply__ignores_local_root_author(self, mock_make, mock_forward, mock_sender):
        post = Post()
        mock_make.return_value = post
        send_reply(self.reply.id, self.reply.activities.first().fid)
        self.assertTrue(mock_sender.called is False)
        self.assertTrue(mock_forward.called is False)

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.forward_entity")
    @patch("socialhome.federate.tasks.make_federable_content")
    def test_send_reply__limited_content(self, mock_make, mock_forward, mock_sender):
        post = Post()
        mock_make.return_value = post
        send_reply(self.limited_reply.id, self.limited_reply.activities.first().fid)
        mock_sender.assert_called_once_with(
            post,
            self.limited_reply.author.federable,
            [self.remote_profile.get_recipient_for_visibility(Visibility.LIMITED)],
            payload_logger=None,
        )

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.forward_entity")
    @patch("socialhome.federate.tasks.make_federable_content")
    def test_send_reply__to_remote_author(self, mock_make, mock_forward, mock_sender):
        post = Post()
        mock_make.return_value = post
        send_reply(self.reply2.id, self.reply2.activities.first().fid)
        mock_sender.assert_called_once_with(post, self.reply2.author.federable, [
            self.remote_content.author.get_recipient_for_visibility(self.reply2.visibility),
        ], payload_logger=None)
        self.assertTrue(mock_forward.called is False)

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.forward_entity")
    @patch("socialhome.federate.tasks.make_federable_content")
    def test_send_reply__to_remote_follower(self, mock_make, mock_forward, mock_sender):
        post = Post()
        mock_make.return_value = post
        send_reply(self.limited_local_reply.id, self.limited_local_reply.activities.first().fid)
        mock_sender.assert_called_once_with(post, self.limited_local_reply.author.federable, [
            self.remote_profile.get_recipient_for_visibility(self.limited_local_reply.visibility),
        ], payload_logger=None)
        self.assertTrue(mock_forward.called is False)


class TestSendShare(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.create_local_and_remote_user()
        Profile.objects.filter(id=cls.profile.id).update(
            rsa_private_key=get_dummy_private_key().exportKey().decode("utf-8")
        )
        cls.profile.refresh_from_db()
        cls.content = ContentFactory(author=cls.remote_profile, visibility=Visibility.PUBLIC)
        cls.limited_content = ContentFactory(author=cls.remote_profile, visibility=Visibility.LIMITED)
        cls.share = ContentFactory(share_of=cls.content, author=cls.profile, visibility=Visibility.PUBLIC)
        cls.limited_share = ContentFactory(
            share_of=cls.limited_content, author=cls.profile, visibility=Visibility.LIMITED
        )
        cls.local_content = LocalContentFactory(visibility=Visibility.PUBLIC)
        cls.local_share = ContentFactory(share_of=cls.local_content, author=cls.profile, visibility=Visibility.PUBLIC)

    @patch("socialhome.federate.tasks.make_federable_content", return_value=None)
    def test_only_public_share_calls_make_federable_content(self, mock_maker):
        send_share(self.limited_share.id, "foo")
        self.assertTrue(mock_maker.called is False)
        send_share(self.share.id, self.share.activities.first().fid)
        mock_maker.assert_called_once_with(self.share)

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.make_federable_content")
    def test_handle_send_is_called(self, mock_maker, mock_send):
        post = Post()
        mock_maker.return_value = post
        send_share(self.share.id, self.share.activities.first().fid)
        mock_send.assert_called_once_with(
            post,
            self.share.author.federable,
            [self.content.author.get_recipient_for_visibility(self.share.visibility)],
            payload_logger=None,
        )

    @patch("socialhome.federate.tasks.make_federable_content", return_value=None)
    @patch("socialhome.federate.tasks.logger.warning")
    def test_warning_is_logged_on_no_entity(self, mock_logger, mock_maker):
        send_share(self.share.id, "foo")
        self.assertTrue(mock_logger.called)

    @override_settings(DEBUG=True)
    @patch("socialhome.federate.tasks.handle_send")
    def test_content_not_sent_in_debug_mode(self, mock_send):
        send_share(self.share.id, "foo")
        self.assertTrue(mock_send.called is False)

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.make_federable_content")
    def test_doesnt_send_to_local_share_author(self, mock_maker, mock_send):
        post = Post()
        mock_maker.return_value = post
        send_share(self.local_share.id, self.local_share.activities.first().fid)
        mock_send.assert_called_once_with(post, self.local_share.author.federable, [], payload_logger=None)


class TestForwardEntity(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        author = UserFactory()
        author.profile.rsa_private_key = get_dummy_private_key().exportKey()
        author.profile.save()
        cls.public_content = PublicContentFactory(author=author.profile)
        cls.remote_reply = PublicContentFactory(parent=cls.public_content, author=ProfileFactory())
        cls.reply = PublicContentFactory(parent=cls.public_content)
        cls.share = PublicContentFactory(share_of=cls.public_content)
        cls.share_reply = PublicContentFactory(parent=cls.share)
        cls.limited_content = LimitedContentFactory(author=author.profile)
        cls.limited_reply = LimitedContentFactory(parent=cls.limited_content)
        cls.remote_limited_reply = LimitedContentFactory(parent=cls.limited_content)
        cls.limited_content.limited_visibilities.set((cls.limited_reply.author, cls.remote_limited_reply.author))

    @patch("socialhome.federate.tasks.handle_send", return_value=None, autospec=True)
    def test_forward_entity(self, mock_send):
        entity = Comment(actor_id=self.reply.author.fid, id=self.reply.fid)
        forward_entity(entity, self.public_content.id)
        expected = {
            self.share_reply.author.get_recipient_for_visibility(Visibility.PUBLIC)["fid"],
            self.remote_reply.author.get_recipient_for_visibility(Visibility.PUBLIC)["fid"],
            self.share.author.get_recipient_for_visibility(Visibility.PUBLIC)["fid"],
        }
        mock_send.assert_called_once_with(
            entity, self.reply.author.federable, ANY, parent_user=self.public_content.author.federable,
            payload_logger=None,
        )
        args, kwargs = mock_send.call_args_list[0]
        self.assertEqual({recipient["fid"] for recipient in args[2]}, expected)

    @patch("socialhome.federate.tasks.handle_send", return_value=None)
    def test_forward_entity__limited_content(self, mock_send):
        entity = Comment(actor_id=self.limited_reply.author.fid, id=self.limited_reply.fid)
        forward_entity(entity, self.limited_content.id)
        mock_send.assert_called_once_with(entity, self.limited_reply.author.federable, [
            self.remote_limited_reply.author.get_recipient_for_visibility(Visibility.LIMITED),
        ], parent_user=self.limited_content.author.federable, payload_logger=None)


class TestGetRemoteFollowers(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = UserFactory()
        cls.local_follower_user = UserFactory()
        cls.local_follower_user.profile.following.add(cls.user.profile)
        cls.remote_follower = ProfileFactory()
        cls.remote_follower.following.add(cls.user.profile)
        cls.remote_follower2 = ProfileFactory()
        cls.remote_follower2.following.add(cls.user.profile)

    def test_all_remote_returned(self):
        followers = _get_remote_followers(self.user.profile, self.user.profile.visibility)
        expected = {self.remote_follower.fid, self.remote_follower2.fid}
        self.assertEqual(
            {follower["fid"] for follower in followers},
            expected,
        )

    def test_exclude_is_excluded(self):
        followers = _get_remote_followers(
            self.user.profile, self.user.profile.visibility, exclude=self.remote_follower.fid,
        )
        self.assertEqual(
            followers,
            [
                self.remote_follower2.get_recipient_for_visibility(self.user.profile.visibility),
            ]
        )


class TestGetLimitedRecipients(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.profile = ProfileFactory()
        cls.limited_content = LimitedContentFactory(author=cls.profile)
        cls.profile2 = ProfileFactory(with_key=True)
        cls.profile3 = ProfileFactory(with_key=True)
        cls.limited_content.limited_visibilities.set((cls.profile2, cls.profile3))

    def test_correct_recipients_returned(self):
        recipients = _get_limited_recipients(self.profile.fid, self.limited_content)
        expected = {self.profile2.fid, self.profile3.fid}
        print(recipients)
        self.assertEqual(
            {recipient['fid'] for recipient in recipients},
            expected,
        )


class TestSendFollow(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = UserFactory()
        cls.profile = cls.user.profile
        cls.remote_profile = ProfileFactory(
            rsa_public_key=get_dummy_private_key().publickey().exportKey(),
        )

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.send_profile")
    @patch("socialhome.federate.tasks.base.Follow", return_value="entity")
    def test_send_follow_change(self, mock_follow, mock_profile, mock_send):
        send_follow_change(self.profile.id, self.remote_profile.id, True)
        mock_send.assert_called_once_with(
            "entity",
            self.profile.federable,
            [self.remote_profile.get_recipient_for_visibility(Visibility.LIMITED)],
            payload_logger=None,
        )
        mock_profile.assert_called_once_with(self.profile.id, recipients=[
            self.remote_profile.get_recipient_for_visibility(Visibility.LIMITED),
        ])


class TestSendProfile(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = UserFactory()
        cls.profile = cls.user.profile
        cls.remote_profile = ProfileFactory()
        cls.remote_profile2 = ProfileFactory()

    @patch("socialhome.federate.tasks.handle_send", autospec=True)
    @patch("socialhome.federate.tasks._get_remote_followers", autospec=True)
    @patch("socialhome.federate.tasks.make_federable_profile", return_value="profile", autospec=True)
    def test_send_local_profile(self, mock_federable, mock_get, mock_send):
        recipients = [
            self.remote_profile.fid,
            self.remote_profile2.fid,
        ]
        mock_get.return_value = recipients
        send_profile(self.profile.id)
        mock_send.assert_called_once_with(
            "profile", self.profile.federable, [
                self.profile.get_recipient_for_matrix_appservice(),
                self.remote_profile.fid,
                self.remote_profile2.fid,
            ], payload_logger=None,
        )

    @patch("socialhome.federate.tasks.make_federable_profile")
    def test_skip_remote_profile(self, mock_make):
        send_profile(self.remote_profile.id)
        self.assertFalse(mock_make.called)

    @patch("socialhome.federate.tasks.handle_send")
    @patch("socialhome.federate.tasks.make_federable_profile", return_value="profile")
    def test_send_to_given_recipients_only(self, mock_federable, mock_send):
        recipients = [self.remote_profile.fid]
        send_profile(self.profile.id, recipients=recipients)
        mock_send.assert_called_once_with("profile", self.profile.federable, recipients, payload_logger=None)
