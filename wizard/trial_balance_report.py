# -*- coding: utf-8 -*-
###############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Aysha Shalin (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC
#    LICENSE (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from odoo import fields, models, _
from datetime import datetime


class TrialBalanceReport(models.TransientModel):
    """ Create new model """
    _name = 'trial.balance.report'
    _description = 'trial balance report'

    def _format_amount_panama(self, amount):
        """Format amount according to Panamanian accounting standards"""
        if amount is None:
            amount = 0.0
        amount = float(amount)
        if amount < 0:
            return "({:,.2f})".format(abs(amount))
        else:
            return "{:,.2f}".format(amount)

    start_date = fields.Date(string="Start Date",
                             help="Select start date to fetch the trial "
                                  "balance data")
    end_date = fields.Date(string="End Date",
                           help="Select end date to fetch the trial "
                                "balance data")
    journals_ids = fields.Many2many('account.journal', string="Journals",
                                    help="Select the journals to added in the"
                                         "trail balance")
    company_id = fields.Many2one('res.company', string="Company",
                                 help="Select the company of the journals",
                                 default=lambda self: self.env.company)
    state = fields.Selection([
        ('posted', _('Posted Entries only')),
        ('draft', _('Include UnPosted Entries')),
    ], tracking=True, string="State", help="Select the state of journal "
                                           "entries which we want to report")

    def button_to_get_pdf(self):
        """ It will create the report using defined query """
        # Base conditions for filtering
        base_conditions = []
        base_parameters = []
        state_value = ""
        currency = self.env.user.company_id.currency_id.symbol
        
        # Company filter
        if self.company_id:
            base_conditions.append("account_move_line.company_id = %s")
            base_parameters.append(self.company_id.id)
        
        # Build WHERE conditions list
        beginning_where_conditions = base_conditions.copy()
        beginning_params = base_parameters.copy()
        
        period_where_conditions = base_conditions.copy()
        period_params = base_parameters.copy()
        
        # State filter
        if self.state == 'posted':
            beginning_where_conditions.append("parent_state = 'posted'")
            period_where_conditions.append("parent_state = 'posted'")
        elif self.state == 'draft':
            beginning_where_conditions.append("parent_state in ('posted', 'draft')")
            period_where_conditions.append("parent_state in ('posted', 'draft')")
        
        # Journal filter
        if self.journals_ids:
            journal_ids = [journal.id for journal in self.journals_ids]
            beginning_where_conditions.append("journal_id IN %s")
            beginning_params.append(tuple(journal_ids))
            period_where_conditions.append("journal_id IN %s")
            period_params.append(tuple(journal_ids))
        
        # Date filters for beginning balance (before start_date)
        if self.start_date:
            beginning_where_conditions.append("account_move_line.date < %s")
            beginning_params.append(self.start_date)
        
        # Date filters for period transactions
        if self.start_date:
            period_where_conditions.append("account_move_line.date >= %s")
            period_params.append(self.start_date)
        if self.end_date:
            period_where_conditions.append("account_move_line.date <= %s")
            period_params.append(self.end_date)
        
        # Build WHERE clauses
        beginning_where = " AND ".join(beginning_where_conditions) if beginning_where_conditions else "1=1"
        period_where = " AND ".join(period_where_conditions) if period_where_conditions else "1=1"
        
        # Calculate beginning balance (before start_date)
        beginning_query = """
            SELECT
                account_id,
                COALESCE(SUM(debit), 0) AS beginning_debit,
                COALESCE(SUM(credit), 0) AS beginning_credit
            FROM account_move_line
            WHERE {}
            GROUP BY account_id
        """.format(beginning_where)
        
        # Calculate period transactions (between start_date and end_date)
        period_query = """
            SELECT
                account_id,
                COALESCE(SUM(debit), 0) AS period_debit,
                COALESCE(SUM(credit), 0) AS period_credit
            FROM account_move_line
            WHERE {}
            GROUP BY account_id
        """.format(period_where)
        
        # Execute queries
        self.env.cr.execute(beginning_query, tuple(beginning_params))
        beginning_data = {row['account_id']: row for row in self.env.cr.dictfetchall()}
        
        self.env.cr.execute(period_query, tuple(period_params))
        period_data = {row['account_id']: row for row in self.env.cr.dictfetchall()}
        
        # Get all accounts that appear in our queries
        # Collect all account IDs from the query results
        account_ids_in_results = set()
        account_ids_in_results.update(beginning_data.keys())
        account_ids_in_results.update(period_data.keys())
        
        # Get accounts by their IDs (this avoids the company_id field issue)
        if account_ids_in_results:
            accounts = self.env['account.account'].browse(list(account_ids_in_results))
        else:
            # If no accounts found, return empty result set
            accounts = self.env['account.account'].browse([])
        
        # Account type mapping for grouping
        account_type_mapping = {
            'asset_receivable': _('Activos'),
            'asset_cash': _('Activos'),
            'asset_current': _('Activos'),
            'asset_non_current': _('Activos'),
            'asset_prepayments': _('Activos'),
            'asset_fixed': _('Activos'),
            'liability_payable': _('Pasivos'),
            'liability_credit_card': _('Pasivos'),
            'liability_current': _('Pasivos'),
            'liability_non_current': _('Pasivos'),
            'equity': _('Patrimonio'),
            'equity_unaffected': _('Patrimonio'),
            'income': _('Ingresos'),
            'income_other': _('Ingresos'),
            'expense': _('Gastos'),
            'expense_depreciation': _('Gastos'),
            'expense_direct_cost': _('Gastos'),
            'off_balance': _('Cuentas de Orden'),
        }
        
        # Combine data and calculate balances
        final_results = []
        grouped_results = {}
        total_beginning_balance = 0.0
        total_ending_balance = 0.0
        total_period_change = 0.0
        total_net_balance = 0.0
        total_debits = 0.0
        total_credits = 0.0
        
        for account in accounts:
            account_id = account.id
            beginning_debit = beginning_data.get(account_id, {}).get('beginning_debit', 0.0) or 0.0
            beginning_credit = beginning_data.get(account_id, {}).get('beginning_credit', 0.0) or 0.0
            period_debit = period_data.get(account_id, {}).get('period_debit', 0.0) or 0.0
            period_credit = period_data.get(account_id, {}).get('period_credit', 0.0) or 0.0
            
            # Calculate balances
            beginning_balance = beginning_debit - beginning_credit
            period_change = period_debit - period_credit
            ending_balance = beginning_balance + period_change
            net_balance = beginning_balance - ending_balance
            
            # Only include accounts that have transactions or balance
            if beginning_balance != 0 or period_debit != 0 or period_credit != 0:
                account_type_name = account_type_mapping.get(account.account_type, _('Otros'))
                
                account_data = {
                    'code': account.code or '',
                    'ac_name': account.name,
                    'account_type': account.account_type,
                    'account_type_name': account_type_name,
                    'beginning_balance': round(beginning_balance, 2),
                    'ending_balance': round(ending_balance, 2),
                    'period_change': round(period_change, 2),
                    'net_balance': round(net_balance, 2),
                    'beginning_balance_formatted': self._format_amount_panama(beginning_balance),
                    'ending_balance_formatted': self._format_amount_panama(ending_balance),
                    'period_change_formatted': self._format_amount_panama(period_change),
                    'net_balance_formatted': self._format_amount_panama(net_balance),
                }
                
                final_results.append(account_data)
                
                # Group by account type
                if account_type_name not in grouped_results:
                    grouped_results[account_type_name] = []
                grouped_results[account_type_name].append(account_data)
                
                total_beginning_balance += beginning_balance
                total_ending_balance += ending_balance
                total_period_change += period_change
                total_net_balance += net_balance
                total_debits += period_debit
                total_credits += period_credit
        
        # Sort by account code within each group
        for group_name in grouped_results:
            grouped_results[group_name].sort(key=lambda x: x['code'] or '')
        
        # Sort final results by account code
        final_results.sort(key=lambda x: x['code'] or '')
        
        # Check if trial balance is balanced (for validation)
        is_balanced = abs(total_debits - total_credits) < 0.01
        
        if self.state:
            # Translate the state value for display
            state_labels = {
                'posted': _('Posted Entries only'),
                'draft': _('Include UnPosted Entries')
            }
            state_value = state_labels.get(self.state, '')
        journals = str(self.journals_ids.mapped('name'))
        result = journals[1:-1].replace("'", "")
        
        # Get company information
        company = self.company_id or self.env.company
        company_name = company.name or ''
        company_vat = company.vat or ''
        company_street = company.street or ''
        company_city = company.city or ''
        company_country = company.country_id.name if company.country_id else ''
        
        # Get user information
        user = self.env.user
        prepared_by = user.name or ''
        prepared_date = datetime.now().strftime('%d/%m/%Y %H:%M')
        
        data = {
            'query': final_results,
            'grouped_query': grouped_results,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'total_beginning_balance': round(total_beginning_balance, 2),
            'total_ending_balance': round(total_ending_balance, 2),
            'total_period_change': round(total_period_change, 2),
            'total_net_balance': round(total_net_balance, 2),
            'total_beginning_balance_formatted': self._format_amount_panama(total_beginning_balance),
            'total_ending_balance_formatted': self._format_amount_panama(total_ending_balance),
            'total_period_change_formatted': self._format_amount_panama(total_period_change),
            'total_net_balance_formatted': self._format_amount_panama(total_net_balance),
            'total_debits': round(total_debits, 2),
            'total_credits': round(total_credits, 2),
            'total_debits_formatted': self._format_amount_panama(total_debits),
            'total_credits_formatted': self._format_amount_panama(total_credits),
            'is_balanced': is_balanced,
            'balance_difference': round(abs(total_debits - total_credits), 2),
            'currency': currency,
            'state': state_value,
            'journals_name': result,
            'company_name': company_name,
            'company_vat': company_vat,
            'company_address': ', '.join(filter(None, [company_street, company_city, company_country])),
            'prepared_by': prepared_by,
            'prepared_date': prepared_date,
        }
        return self.env.ref(
            'trial_balance_pdf.action_report_trial_balance').report_action(
            self, data=data)
