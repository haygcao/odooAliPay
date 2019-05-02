# -*- coding: utf-8 -*-
import base64
import datetime
import json
import logging
import os
import qrcode
from alipay.aop.api.request.AlipayTradePrecreateRequest import AlipayTradePrecreateRequest
from alipay.aop.api.domain.AlipayTradePrecreateModel import AlipayTradePrecreateModel
from alipay.aop.api.request.AlipayTradeQueryRequest import AlipayTradeQueryRequest
from alipay.aop.api.domain.AlipayTradeQueryModel import AlipayTradeQueryModel
from odoo import fields, models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AliPayPrecreate(models.Model):
    _description = '当面付'
    _name = 'alipay.precreate'
    _inherit = ['mail.thread']
    _rec_name = 'out_biz_no'

    out_biz_no = fields.Char(string='订单编号')
    subject = fields.Char(string=u'订单标题')
    total_amount = fields.Float(string=u'订单总金额', digits=(13, 2), default=0.0)
    line_ids = fields.One2many(comodel_name='alipay.precreate.line', inverse_name='precreate_id', string=u'商品列表')
    company_id = fields.Many2one(comodel_name='res.company', string=u'公司',
                                 default=lambda self: self.env.user.company_id.id)
    state = fields.Selection(string=u'状态', selection=[('00', '草稿'), ('01', '预交易'), ('02', '已支付'), ('03', '未支付')],
                             default='00')
    precreate_time = fields.Datetime(string=u'生成交易时间')
    pay_time = fields.Datetime(string=u'支付确认时间')
    body = fields.Text(string=u'备注')
    qr_code = fields.Char(string='二维码码串')
    trade_no = fields.Char(string='支付宝交易号')
    alipay_user = fields.Many2one(comodel_name='alipay.users', string=u'支付用户')

    @api.model
    def create(self, values):
        values['out_biz_no'] = self.env['ir.sequence'].sudo().next_by_code('alipay.precreate.code')
        return super(AliPayPrecreate, self).create(values)

    @api.multi
    def summit_precreate(self):
        for res in self:
            client = self.env['alipay.transfer'].get_config_client()
            transfer_model = AlipayTradePrecreateModel()
            transfer_model.out_trade_no = res.out_biz_no  # 编号
            transfer_model.total_amount = res.total_amount  # 订单总金额
            transfer_model.subject = res.subject  # 订单标题
            transfer_model.body = res.body  # 备注
            # 获取产品列表
            pro_list = list()
            for pro in res.line_ids:
                pro_list.append({
                    'goods_id': pro.goods_id,
                    'goods_name': pro.product_id.name,
                    'quantity': pro.quantity,
                    'price': pro.price,
                })
            transfer_model.goods_detail = pro_list   # 商品列表
            transfer_request = AlipayTradePrecreateRequest(transfer_model)
            result = client.execute(transfer_request)
            logging.info(">>>支付宝预交易结果:{}".format(result))
            result = json.loads(result, 'utf-8')
            if result.get('code') != '10000':
                raise UserError("预交易失败！原因为:{}".format(result.get('sub_msg')))
            else:
                res.write({
                    'state': '01',
                    'precreate_time': datetime.datetime.now(),
                    'qr_code': result.get('qr_code'),
                })
                res.message_post(body="创建预交易结果:{}".format(result.get('msg')), message_type='notification')

    @api.multi
    def open_qr_code(self):
        for res in self:
            action = self.env.ref('odoo_alipay.alipay_precreate_qr_code_action').read()[0]
            action['context'] = {
                'precreate_id': res.id,
            }
            return action


class AliPayPrecreateProduct(models.Model):
    _name = 'alipay.precreate.line'
    _description = "当面付产品列表"
    _rec_name = 'precreate_id'

    precreate_id = fields.Many2one(comodel_name='alipay.precreate', string=u'当面付', ondelete='cascade')
    product_id = fields.Many2one(comodel_name='product.template', string=u'产品')
    goods_id = fields.Char(string='产品编号')
    quantity = fields.Integer(string='数量')
    price = fields.Float(string='单价', digits=(13, 2), default=0.0)


class AliPayPrecreateQrCode(models.TransientModel):
    _name = 'alipay.precreate.qr.code'
    _description = "当面付二维码"
    _rec_name = 'out_biz_no'

    out_biz_no = fields.Char(string='订单编号')
    subject = fields.Char(string=u'订单标题')
    image = fields.Binary(attachment=True, string="付款二维码")
    image_medium = fields.Binary(string='Medium-sized image', attachment=True)
    image_small = fields.Binary(string='Small-sized image', attachment=True)
    precreate_id = fields.Many2one(comodel_name='alipay.precreate', string=u'当面付', ondelete='cascade')

    @api.model
    def default_get(self, fields):
        """获取资产原有的信息"""
        res = super(AliPayPrecreateQrCode, self).default_get(fields)
        precreate = self.env['alipay.precreate'].browse(self.env.context.get('precreate_id'))
        res.update({
            'precreate_id': precreate.id,
            'out_biz_no': precreate.out_biz_no,
            'subject': precreate.subject,
            'image': self.qr_code(precreate.qr_code)
        })
        return res

    @api.model
    def qr_code(self, qr_code_url):
        """
        生成二维码
        :param qr_code_url: 二维码里的链接
        :return:
        """
        qr = qrcode.QRCode(
            version=4,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=100,
            border=1,
        )
        qr.add_data(data=qr_code_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="red", back_color="white")
        filename = "precreate_img.png"
        # img = qrcode.make(qr_code_url)
        img.save(filename)
        img_file = open(filename, "rb")
        os.unlink(filename)
        return base64.b64encode(img_file.read())

    @api.multi
    def precreate(self):
        for res in self:
            client = self.env['alipay.transfer'].get_config_client()
            alipay_model = AlipayTradeQueryModel()
            alipay_model.out_trade_no = res.out_biz_no  # 编号
            alipay_request = AlipayTradeQueryRequest(alipay_model)
            result = client.execute(alipay_request)
            logging.info(">>>支付宝查询交易结果:{}".format(result))
            result = json.loads(result, 'utf-8')
            if result.get('code') == '10000':
                if result.get('trade_status') == 'WAIT_BUYER_PAY':
                    res.precreate_id.message_post(body="等待买家付款", message_type='notification')
                elif result.get('trade_status') == 'TRADE_CLOSED':
                    res.precreate_id.message_post(body="未付款交易超时关闭，或支付完成后全额退款", message_type='notification')
                    res.precreate_id.write({
                        'state': '03',
                        'pay_time': datetime.datetime.now(),
                    })
                elif result.get('trade_status') == 'TRADE_SUCCESS':
                    res.precreate_id.message_post(body="交易支付成功", message_type='notification')
                    user = self.create_alipay_user(result)
                    res.precreate_id.write({
                        'state': '02',
                        'pay_time': datetime.datetime.now(),
                        'trade_no': result.get('trade_no'),
                        'alipay_user': user.id,
                    })
                elif result.get('trade_status') == 'TRADE_FINISHED':
                    res.precreate_id.message_post(body="交易结束，不可退款", message_type='notification')
            else:
                res.precreate_id.message_post(body="等待扫码付款...", message_type='notification')

    @api.model
    def create_alipay_user(self, result):
        user = self.env['alipay.users'].sudo().search([('user_id', '=', result.get('buyer_user_id'))])
        if not user:
            return self.env['alipay.users'].sudo().create({
                'name': result.get('buyer_logon_id'),
                'login_id': result.get('buyer_logon_id'),
                'user_id': result.get('buyer_user_id'),
                'user_type': result.get('buyer_user_type')
            })


