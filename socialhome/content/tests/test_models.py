# -*- coding: utf-8 -*-
import pytest
from django.db import IntegrityError

from socialhome.content.enums import ContentTarget
from socialhome.content.models import Post, Content
from socialhome.content.tests.factories import PostFactory
from socialhome.users.tests.factories import ProfileFactory


@pytest.mark.usefixtures("db")
class TestPostModel(object):
    def test_post_model_create(self):
        Post.objects.create(text="foobar", guid="barfoo", author=ProfileFactory())

    def test_post_gets_guid_on_save_with_user(self):
        post = Post(text="foobar")
        post.save(author=ProfileFactory())
        assert post.guid

    def test_post_raises_on_save_without_user(self):
        post = Post(text="foobar")
        with pytest.raises(IntegrityError):
            post.save()

    def test_post_render(self):
        post = Post.objects.create(text="# Foobar", guid="barfoo", author=ProfileFactory())
        assert post.render() == "<h1>Foobar</h1>"


@pytest.mark.usefixtures("db")
class TestContentModel(object):
    def test_content_model_create(self):
        Content.objects.create(
            target=ContentTarget.PROFILE,
            author=ProfileFactory(),
            content_object=PostFactory()
        )
