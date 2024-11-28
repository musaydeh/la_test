# Copyright (C) Softhealer Technologies.

from datetime import timedelta, date
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

class Attachment(models.Model):
    _inherit = 'ir.attachment'

    pdc_id = fields.Many2one('pdc.wizard')

class PDC_wizard(models.Model):
    _name = "pdc.wizard"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "PDC Wizard"

    name = fields.Char("Name", default='New', readonly=1, tracking=True)
    payment_type = fields.Selection([
        ('receive_money', 'Receive Money'), 
        ('send_money', 'Send Money')
    ], string="Payment Type", default='receive_money', tracking=True)
    partner_id = fields.Many2one('res.partner', string="Partner", tracking=True)
    payment_amount = fields.Monetary("Payment Amount", tracking=True)
    currency_id = fields.Many2one('res.currency', string="Currency", 
                                 default=lambda self: self.env.company.currency_id, 
                                 tracking=True, required=True)
    reference = fields.Char("Cheque Reference", tracking=True)
    journal_id = fields.Many2one('account.journal', string="Payment Journal", 
                                domain=[('type', '=', 'bank')], tracking=True)
    payment_date = fields.Date("Payment Date", default=fields.Date.today(), required=1, tracking=True)
    due_date = fields.Date("Due Date", tracking=True)
    memo = fields.Char("Memo", tracking=True)
    agent = fields.Char("Agent", tracking=True)
    bank_id = fields.Many2one('res.bank', string="Bank", tracking=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Cheque Image')
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company, tracking=True)
    invoice_id = fields.Many2one('account.move', string="Invoice/Bill", tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('registered', 'Registered'),
        ('endorsed', 'Endorsed'),
        ('returned', 'Returned'),
        ('deposited', 'Deposited'),
        ('bounced', 'Bounced'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')
    ], string="State", default='draft', tracking=True)
    deposited_debit = fields.Many2one('account.move.line')
    deposited_credit = fields.Many2one('account.move.line')
    invoice_ids = fields.Many2many('account.move')
    account_move_ids = fields.Many2many('account.move', compute="compute_account_moves")
    done_date = fields.Date(string="Done Date", readonly=True, tracking=True)
    deposit_move_id = fields.Many2one("account.move", copy=False)
    endorsement_cheque = fields.Boolean(string="Endorsement Cheque")
    endorse_partner_id = fields.Many2one("res.partner", string="Endorse to Partner")

    def unlink(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("You can only delete draft state PDC"))
        return super().unlink()

    @api.model
    def create(self, vals):
        if vals.get('payment_type') == 'receive_money':
            vals['name'] = self.env['ir.sequence'].next_by_code('pdc.payment.customer')
        elif vals.get('payment_type') == 'send_money':
            vals['name'] = self.env['ir.sequence'].next_by_code('pdc.payment.vendor')
        return super().create(vals)

    @api.constrains("endorse_partner_id", "partner_id")
    def check_endorse_partner(self):
        for pdc_wizard in self.filtered(lambda pdc: pdc.endorse_partner_id):
            if pdc_wizard.endorse_partner_id == pdc_wizard.partner_id:
                raise ValidationError(_("Endorse to partner must not be the same partner"))

    @api.depends('payment_type', 'partner_id')
    def compute_account_moves(self):
        for record in self:
            record.account_move_ids = False
            domain = [
                ('partner_id', '=', record.partner_id.id),
                ('payment_state', '!=', 'paid'),
                ('amount_residual', '!=', 0.0),
                ('state', '=', 'posted')
            ]

            if record.payment_type == 'receive_money':
                domain.extend([('move_type', '=', 'out_invoice')])
            else:
                domain.extend([('move_type', '=', 'in_invoice')])

            moves = self.env['account.move'].search(domain)
            record.account_move_ids = moves.ids

    @api.onchange("payment_type")
    def onchange_payment_type(self):
        self.endorsement_cheque = False

    @api.onchange("endorsement_cheque")
    def onchange_endorsement_cheque(self):
        self.journal_id = False
        self.endorse_partner_id = False

    def check_payment_amount(self):
        if self.payment_amount <= 0.0:
            raise UserError(_("Amount must be greater than zero!"))

    def check_pdc_account(self):
        if self.payment_type == 'receive_money':
            if not self.env.company.pdc_customer:
                raise UserError(_("Please Set PDC payment account for Customer!"))
            return self.env.company.pdc_customer.id
        else:
            if not self.env.company.pdc_vendor:
                raise UserError(_("Please Set PDC payment account for Supplier!"))
            return self.env.company.pdc_vendor.id

    def get_partner_account(self):
        if self.payment_type == 'receive_money':
            return self.partner_id.property_account_receivable_id.id
        return self.partner_id.property_account_payable_id.id

    def get_debit_move_line(self, account):
        currency_company = self.company_id.currency_id
        currency = self.currency_id
        debit = self.payment_amount

        if currency_company != currency:
            debit = self.currency_id._convert(debit, currency_company, self.company_id, self.payment_date)

        return {
            'pdc_id': self.id,
            'currency_id': currency.id,
            'account_id': account,
            'amount_currency': self.payment_amount,
            'debit': debit,
            'ref': self.memo,
            'date': self.payment_date,
            'date_maturity': self.due_date,
        }

    def get_credit_move_line(self, account):
        currency_company = self.company_id.currency_id
        currency = self.currency_id
        credit = self.payment_amount

        if currency_company != currency:
            credit = self.currency_id._convert(credit, currency_company, self.company_id, self.payment_date)

        return {
            'pdc_id': self.id,
            'currency_id': currency.id,
            'account_id': account,
            'amount_currency': -self.payment_amount,
            'credit': credit,
            'ref': self.memo,
            'date': self.payment_date,
            'date_maturity': self.due_date,
        }

    def get_move_vals(self, debit_line, credit_line):
        ref = self.memo or ""
        journal = self.journal_id
        if self.endorsement_cheque:
            ref = _("Cheque Endorsement") + ref

            if not self.company_id.endorsement_journal_id:
                raise UserError(_("Check endorsement journal in settings"))

            journal = self.company_id.endorsement_journal_id
            debit_line.update({'name': ref})
            credit_line.update({'name': ref})

        return {
            'pdc_id': self.id,
            'date': self.payment_date,
            'journal_id': journal.id,
            'currency_id': self.currency_id.id,
            'ref': ref,
            'line_ids': [(0, 0, debit_line), (0, 0, credit_line)]
        }

    def action_register(self):
        self.check_payment_amount()

        if self.invoice_ids:
            list_amount_residuals = self.invoice_ids.mapped('amount_residual')
            amount = (self.currency_id.round(sum(list_amount_residuals)) if self.currency_id else 
                     round(sum(list_amount_residuals), 2))

            if self.payment_amount > amount:
                raise UserError(_("Payment amount is greater than total invoice/bill amount!"))

        pdc_account = self.check_pdc_account()
        partner_account = self.get_partner_account()

        if self.payment_type == 'receive_money':
            move_line_vals_debit = self.get_debit_move_line(pdc_account)
            move_line_vals_credit = self.get_credit_move_line(partner_account)
            move_line_vals_credit.update({"partner_id": self.partner_id.id})

            if self.endorsement_cheque:
                move_line_vals_debit.update({
                    "account_id": self.endorse_partner_id.property_account_payable_id.id,
                    "partner_id": self.endorse_partner_id.id
                })
        else:
            move_line_vals_debit = self.get_debit_move_line(partner_account)
            move_line_vals_credit = self.get_credit_move_line(pdc_account)
            move_line_vals_debit.update({"partner_id": self.partner_id.id})

        move_vals = self.get_move_vals(move_line_vals_debit, move_line_vals_credit)
        deposit_move = self.env['account.move'].create(move_vals)

        self.write({'state': 'registered', 'deposit_move_id': deposit_move.id})

    def action_endorse(self):
        if self.state != "registered" or not self.endorsement_cheque:
            return

        if self.deposit_move_id.state == "draft":
            self.deposit_move_id.action_post()

        return self.write({"state": "endorsed"})

    def action_returned(self):
        self.check_payment_amount()
        self.write({'state': 'returned'})

    def action_deposited(self):
        self.check_payment_amount()
        self.deposit_move_id.action_post()
        self.write({
            'state': 'deposited',
            'deposited_debit': self.deposit_move_id.line_ids.filtered(lambda x: x.debit > 0),
            'deposited_credit': self.deposit_move_id.line_ids.filtered(lambda x: x.credit > 0)
        })

    def action_bounced(self):
        move = self.env['account.move']
        self.check_payment_amount()
        pdc_account = self.check_pdc_account()
        partner_account = self.get_partner_account()

        if self.payment_type == 'receive_money':
            move_line_vals_debit = self.get_debit_move_line(partner_account)
            move_line_vals_credit = self.get_credit_move_line(pdc_account)
        else:
            move_line_vals_debit = self.get_debit_move_line(pdc_account)
            move_line_vals_credit = self.get_credit_move_line(partner_account)

        name_prefix = 'PDC Payment :' if self.memo else 'PDC Payment'
        move_line_vals_debit.update({'name': f"{name_prefix}{self.memo or ''}"})
        move_line_vals_credit.update({'name': f"{name_prefix}{self.memo or ''}"})

        move_vals = self.get_move_vals(move_line_vals_debit, move_line_vals_credit)
        move_id = move.create(move_vals)
        move_id.action_post()

        self.write({'state': 'bounced'})

    def action_done(self):
        move = self.env['account.move']
        self.check_payment_amount()
        pdc_account = self.check_pdc_account()
        bank_account = self.journal_id._get_journal_inbound_outstanding_payment_accounts()
        bank_account = bank_account[0].id if bank_account else False

        if self.payment_type == 'receive_money':
            move_line_vals_debit = self.get_debit_move_line(bank_account)
            move_line_vals_credit = self.get_credit_move_line(pdc_account)
        else:
            move_line_vals_debit = self.get_debit_move_line(pdc_account)
            move_line_vals_credit = self.get_credit_move_line(bank_account)

        name_prefix = 'PDC Payment :' if self.memo else 'PDC Payment'
        move_line_vals_debit.update({'name': f"{name_prefix}{self.memo or ''}"})
        move_line_vals_credit.update({'name': f"{name_prefix}{self.memo or ''}"})

        move_vals = self.get_move_vals(move_line_vals_debit, move_line_vals_credit)
        move_id = move.create(move_vals)
        move_id.action_post()

        if self.invoice_ids:
            payment_amount = self.payment_amount
            for invoice in self.invoice_ids:
                self._reconcile_payment(invoice, move_id, payment_amount)
                payment_amount -= invoice.amount_residual

        self.write({
            'state': 'done',
            'done_date': fields.Date.today(),
        })

    def _reconcile_payment(self, invoice, move_id, payment_amount):
        if payment_amount <= 0:
            return

        amount = min(payment_amount, invoice.amount_residual)
        if self.payment_type == 'receive_money':
            debit_move = self.env['account.move.line'].search([
                ('move_id', '=', invoice.id),
                ('debit', '>', 0.0)
            ], limit=1)
            credit_move = self.env['account.move.line'].search([
                ('move_id', '=', move_id.id),
                ('credit', '>', 0.0)
            ], limit=1)
        else:
            credit_move = self.env['account.move.line'].search([
                ('move_id', '=', invoice.id),
                ('credit', '>', 0.0)
            ], limit=1)
            debit_move = self.env['account.move.line'].search([
                ('move_id', '=', move_id.id),
                ('debit', '>', 0.0)
            ], limit=1)

        if debit_move and credit_move:
            self._create_reconciliation(debit_move, credit_move, amount)
            self._create_reconciliation(self.deposited_debit, self.deposited_credit, amount)

            if invoice.amount_residual == 0:
                self._create_full_reconciliation(invoice, debit_move, credit_move)

    def _create_reconciliation(self, debit_move, credit_move, amount):
        self.env['account.partial.reconcile'].create({
            'debit_move_id': debit_move.id,
            'credit_move_id': credit_move.id,
            'amount': amount,
            'debit_amount_currency': amount,
            'credit_amount_currency': amount,
        })

    def _create_full_reconciliation(self, invoice, debit_move, credit_move):
        reconcile_lines = debit_move | credit_move
        if invoice.amount_residual == 0:
            self.env['account.full.reconcile'].create({
                'reconciled_line_ids': [(6, 0, reconcile_lines.ids)]
            })

    def action_cancel(self):
        moves_to_reverse = self.env['account.move'].search([('pdc_id', '=', self.id)])
        
        for move in moves_to_reverse:
            if move.state == "draft":
                move.button_cancel()
            elif move.state == "posted":
                reverse_move = move._reverse_moves(
                    default_values_list=[{
                        'date': move._get_accounting_date(move.date, move._affect_tax_report()),
                        'ref': _("Reversal of: %s") % move.name
                    }],
                    cancel=True
                )
                reverse_move.action_post()

        self.write({'state': 'cancel'})

    @api.model
    def notify_customer_due_date(self):
        if not self.env.company.is_cust_due_notify:
            return

        notify_dates = []
        for day in range(1, 6):
            notify_day = getattr(self.env.company, f'notify_on_{day}', False)
            if notify_day:
                notify_dates.append(fields.Date.today() + timedelta(days=int(notify_day) * -1))

        records = self.search([
            ('payment_type', '=', 'receive_money'),
            ('due_date', 'in', notify_dates)
        ])

        for record in records:
            self._send_notifications(record, 'customer')

    @api.model
    def notify_vendor_due_date(self):
        if not self.env.company.is_vendor_due_notify:
            return

        notify_dates = []
        for day in range(1, 6):
            notify_day = getattr(self.env.company, f'notify_on_{day}_vendor', False)
            if notify_day:
                notify_dates.append(fields.Date.today() + timedelta(days=int(notify_day) * -1))

        records = self.search([
            ('payment_type', '=', 'send_money'),
            ('due_date', 'in', notify_dates)
        ])

        for record in records:
            self._send_notifications(record, 'vendor')

    def _send_notifications(self, record, partner_type):
        is_notify_to_partner = getattr(self.env.company, f'is_notify_to_{partner_type}')
        is_notify_to_user = getattr(self.env.company, f'is_notify_to_user_{partner_type}' if partner_type == 'vendor' else 'is_notify_to_user')
        user_ids = getattr(self.env.company, f'sh_user_ids_{partner_type}' if partner_type == 'vendor' else 'sh_user_ids')

        if is_notify_to_partner:
            template = self.env.ref('sh_pdc.sh_pdc_company_to_customer_notification_1')
            template.send_mail(record.id, force_send=True)

        if is_notify_to_user and user_ids:
            emails = user_ids.mapped('partner_id.email')
            if emails:
                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                view_id = self.env.ref('sh_pdc.sh_pdc_payment_form_view').id
                url = f"{base_url}/web#id={record.id}&model=pdc.wizard&view_type=form&view_id={view_id}"
                
                template = self.env.ref('sh_pdc.sh_pdc_company_to_int_user_notification_1')
                template.with_context(customer_url=url).send_mail(
                    record.id,
                    email_values={'email_to': ','.join(emails)},
                    force_send=True
                )

    def action_state_draft(self):
        for record in self:
            if record.state not in ('done', 'endorsed', 'cancel'):
                raise UserError(_('Only done, endorsed and cancel state PDC can be reset to draft'))

            moves = self.env['account.move'].search([('pdc_id', '=', record.id)])
            for move in moves:
                move.button_draft()
                move.line_ids.unlink()
                move.unlink()

            record.write({
                'state': 'draft',
                'done_date': False
            })

    def action_state_register(self):
        if not self:
            return

        if len(set(self.mapped('state'))) > 1:
            raise UserError(_("States must be same!"))

        if self[0].state != 'draft':
            raise UserError(_("Only Draft state PDC check can switch to Register state!"))

        for record in self:
            record.action_register()

    def action_state_return(self):
        if not self:
            return

        if len(set(self.mapped('state'))) > 1:
            raise UserError(_("States must be same!"))

        if self[0].state != 'registered':
            raise UserError(_("Only Register state PDC check can switch to return state!"))

        for record in self:
            record.action_returned()

    def action_state_deposit(self):
        if not self:
            return

        if len(set(self.mapped('state'))) > 1:
            raise UserError(_("States must be same!"))

        if self[0].state not in ['registered', 'returned', 'bounced']:
            raise UserError(_("Only Register, Return and Bounce state PDC check can switch to Deposit state!"))

        for record in self:
            record.action_deposited()

    def action_state_bounce(self):
        if not self:
            return

        if len(set(self.mapped('state'))) > 1:
            raise UserError(_("States must be same!"))

        if self[0].state != 'deposited':
            raise UserError(_("Only Deposit state PDC check can switch to Bounce state!"))

        for record in self:
            record.action_bounced()

    def action_state_done(self):
        if not self:
            return

        if len(set(self.mapped('state'))) > 1:
            raise UserError(_("States must be same!"))

        if self[0].state != 'deposited':
            raise UserError(_("Only Deposit state PDC check can switch to Done state!"))

        for record in self:
            record.action_done()

    def action_state_cancel(self):
        if not self:
            return

        if len(set(self.mapped('state'))) > 1:
            raise UserError(_("States must be same!"))

        if self[0].state not in ['registered', 'returned', 'bounced']:
            raise UserError(_("Only Register, Return and Bounce state PDC check can switch to Cancel state!"))

        for record in self:
            record.action_cancel()