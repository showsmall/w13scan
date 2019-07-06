#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @Time    : 2019/7/4 10:18 PM
# @Author  : w8ay
# @File    : loader.py
import re
from urllib.parse import unquote
from urllib.parse import urlparse

import requests

from lib.baseproxy import HttpTransfer
from lib.common import paramToDict, get_links, get_parent_paths
from lib.const import JSON_RECOGNITION_REGEX, POST_HINT, XML_RECOGNITION_REGEX, \
    JSON_LIKE_RECOGNITION_REGEX, ARRAY_LIKE_RECOGNITION_REGEX, MULTIPART_RECOGNITION_REGEX, DEFAULT_GET_POST_DELIMITER, \
    PLACE, logoutParams
from lib.controller import task_push
from lib.data import KB
from lib.plugins import PluginBase


class FakeReq(HttpTransfer):

    def __init__(self, url, headers: dict):
        HttpTransfer.__init__(self)

        self.https = False
        self.urlparse = p = urlparse(url)
        port = 80
        if p.scheme == "https":
            port = 443
            self.https = True
        hostname = p.netloc
        if ":" in p.netloc:
            try:
                hostname, port = p.netloc.split(":")
                port = int(port)
            except:
                hostname = p.netloc
                port = 80
        self.hostname = hostname
        self.port = port

        self.command = 'GET'
        self.path = p.path + p.query
        self.request_version = 1.1

        # self.urlparse = None
        self.netloc = "{}://{}{}".format(p.scheme, p.netloc, p.path)
        self.params = paramToDict(p.query, place=PLACE.GET)

        self._header = headers
        self._body = None


class FakeResp(HttpTransfer):

    def __init__(self, resp: requests.Response):

        HttpTransfer.__init__(self)

        self.response_version = 1.1
        self.status = resp.status_code
        self.reason = resp.reason
        self._body = resp.content
        self._headers = resp.headers

    def get_body_str(self, decoding='utf-8'):
        if decoding:
            try:
                return self.get_body_data().decode(decoding)
            except Exception as e:
                return ''
        return self.get_body_data().decode('utf-')


class W13SCAN(PluginBase):
    type = 'loader'
    desc = '''Loader插件对请求以及响应进行解析，从而调度更多插件运行'''
    name = 'plugin loader'

    def audit(self):
        method = self.requests.command  # 请求方式 GET or POST
        headers = self.requests.get_headers()  # 请求头 dict类型
        url = self.build_url()  # 请求完整URL
        data = self.requests.get_body_data().decode()  # POST 数据

        resp_data = self.response.get_body_data()  # 返回数据 byte类型
        resp_str = self.response.get_body_str()  # 返回数据 str类型 自动解码
        resp_headers = self.response.get_headers()  # 返回头 dict类型

        p = self.requests.urlparse = urlparse(url)
        netloc = self.requests.netloc = "{}://{}{}".format(p.scheme, p.netloc, p.path)

        if method == "POST":
            data = unquote(data, 'utf-8')
            # todo 自动识别编码解码

            if re.search('([^=]+)=([^%s]+%s?|\Z)' % (DEFAULT_GET_POST_DELIMITER, DEFAULT_GET_POST_DELIMITER),
                         data):
                self.requests.post_hint = POST_HINT.NORMAL
                self.requests.post_data = paramToDict(data, place=PLACE.POST, hint=self.requests.post_hint)

            elif re.search(JSON_RECOGNITION_REGEX, data):
                self.requests.post_hint = POST_HINT.JSON
                self.requests.post_data = paramToDict(data, place=PLACE.POST, hint=self.requests.post_hint)

            elif re.search(XML_RECOGNITION_REGEX, data):
                self.requests.post_hint = POST_HINT.XML

            elif re.search(JSON_LIKE_RECOGNITION_REGEX, data):
                self.requests.post_hint = POST_HINT.JSON_LIKE

            elif re.search(ARRAY_LIKE_RECOGNITION_REGEX, data):
                self.requests.post_hint = POST_HINT.ARRAY_LIKE
                self.requests.post_data = paramToDict(data, place=PLACE.POST, hint=self.requests.post_hint)

            elif re.search(MULTIPART_RECOGNITION_REGEX, data):
                self.requests.post_hint = POST_HINT.MULTIPART

            # 支持自动识别并转换参数的类型有 NORMAL,JSON,ARRAY-LIKE
            if self.requests.post_hint and self.requests.post_hint in [POST_HINT.NORMAL, POST_HINT.JSON,
                                                                       POST_HINT.ARRAY_LIKE]:
                if KB["spiderset"].add(netloc, self.requests.post_data.keys(), 'PostScan'):
                    task_push('PostScan', self.requests, self.response)
            elif self.requests.post_hint is None:
                print("post data数据识别失败")

        elif method == "GET":
            data = unquote(p.query, 'utf-8')
            # todo 自动识别编码解码
            params = paramToDict(data, place=PLACE.GET)
            self.requests.params = params
            if KB["spiderset"].add(netloc, self.requests.params.keys(), 'PerFile'):
                task_push('PerFile', self.requests, self.response)

        # Send PerScheme
        domain = "{}://{}".format(p.scheme, p.netloc)
        if KB["spiderset"].add(domain, '', 'PerScheme'):
            task_push('PerScheme', self.requests, self.response)

        # Collect from response
        links = get_links(resp_str, url, True)
        for link in set(links):
            is_continue = True
            for item in logoutParams:
                if link.lower() in item:
                    is_continue = False
            if not is_continue:
                continue
            try:
                # todo 超过5M拒绝请求
                r = requests.get(link, headers=headers)
                req = FakeReq(link, headers)
                resp = FakeResp(r)
            except:
                continue

            if KB["spiderset"].add(req.netloc, req.params.keys(), 'PerFile'):
                task_push('PerFile', req, resp)

        # Collect directory from response

        urls = set(get_parent_paths(url))
        for link in set(links):
            urls |= set(get_parent_paths(link))
        for i in urls:
            try:
                r = requests.get(i, headers=headers)
                req = FakeReq(i, headers)
                resp = FakeResp(r)
            except:
                continue
            if KB["spiderset"].add(req.netloc, req.params.keys(), 'PerFolder'):
                task_push('PerFolder', req, resp)