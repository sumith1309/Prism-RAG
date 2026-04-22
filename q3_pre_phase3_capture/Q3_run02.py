# Q3 run 2/10
# status: PASS  latency: 12.6s
# query: We're heading into IPO. Which of our biggest accounts in regulated Asian markets are being managed by people who don't have ESOPs and haven't bothered with any certifications?
# ------------------------------------------------------------------------

tier1_asia = df_customers[
    (df_customers['tier'] == 'Tier 1') &
    (df_customers['country'].isin(['India', 'Japan', 'South Korea']))
].copy()

with_am = pd.merge(
    tier1_asia,
    df_employees[['employee_id', 'first_name', 'last_name', 'level', 'job_title', 'department_id']],
    left_on='account_manager_employee_id',
    right_on='employee_id',
    how='left'
)

no_esop = with_am[~with_am['level'].isin(['L5', 'L6', 'L7', 'L8'])].copy()

CERT_RE = r'AWS|Azure|Google|GCP|CKA|CKAD|CKS|CISSP|CIPP|CISM|PMP|Scrum|ML Engineer'
certified_emp_ids = set(
    df_training_compliance[
        (df_training_compliance['module_name'].str.contains(CERT_RE, case=False, regex=True, na=False)) &
        (df_training_compliance['status'] == 'Completed')
    ]['employee_id'].dropna()
)

result = no_esop[~no_esop['employee_id'].isin(certified_emp_ids)][
    ['customer_id', 'customer_name', 'country', 'tier', 'arr_inr_lakhs',
     'account_manager_employee_id', 'first_name', 'last_name', 'level', 'job_title']
].drop_duplicates(subset=['customer_id']).sort_values('arr_inr_lakhs', ascending=False)