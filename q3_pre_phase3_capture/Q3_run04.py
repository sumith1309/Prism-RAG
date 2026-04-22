# Q3 run 4/10
# status: PASS  latency: 14.8s
# query: We're heading into IPO. Which of our biggest accounts in regulated Asian markets are being managed by people who don't have ESOPs and haven't bothered with any certifications?
# ------------------------------------------------------------------------

tier1_asia = df_customers[
    (df_customers['tier'] == 'Tier 1') &
    (df_customers['country'].isin(['India', 'Japan', 'South Korea']))
].copy()

with_am = tier1_asia.merge(
    df_employees[['employee_id', 'first_name', 'last_name', 'level', 'job_title', 'department_id']],
    left_on='account_manager_employee_id',
    right_on='employee_id',
    how='left'
)

no_esop = with_am[~with_am['level'].isin(['L5', 'L6', 'L7', 'L8'])].copy()

cert_filter = (
    df_training_compliance['module_name'].isin([
        'AWS Solutions Architect (Professional)',
        'CIPP/A',
        'CKA - Kubernetes Administrator',
        'Google Professional ML Engineer'
    ]) &
    (df_training_compliance['status'] == 'Completed')
)

certified_emp_ids = set(
    df_training_compliance.loc[cert_filter, 'employee_id'].dropna().unique()
)

result = (
    no_esop[~no_esop['employee_id'].isin(certified_emp_ids)][
        ['customer_id', 'customer_name', 'country', 'tier', 'arr_inr_lakhs',
         'account_manager_employee_id', 'first_name', 'last_name', 'level', 'job_title']
    ]
    .drop_duplicates(subset=['customer_id'])
    .sort_values('arr_inr_lakhs', ascending=False)
    .reset_index(drop=True)
)