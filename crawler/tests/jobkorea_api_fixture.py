"""Synthetic JobKorea XML API responses (guide V4.1 shape). Invented ids, titles and companies only."""


def item(gi_no, *, title=None, company=None, area='I010,B180', job_type='1', w_date='20261110',
         end_date='20261231', jk_url=None, extra=''):
    title = f'데이터 엔지니어 채용 {gi_no}' if title is None else title
    company = f'합성회사{gi_no % 97}' if company is None else company
    jk_url = (f'http://www.jobkorea.co.kr/Recruit/GI_Read/{gi_no}?Oem_Code=C900&amp;api=SECRET-TOKEN'
              if jk_url is None else jk_url)
    company_xml = '' if company == '' else f'<C_Name>{company}</C_Name>'
    return (f'<Items><GI_No>{gi_no}</GI_No>'
            f'<C_URL>http://www.jobkorea.co.kr/Recruit/Co_Read/C/x?Oem_Code=C900&amp;api=SECRET-TOKEN</C_URL>'
            f'{company_xml}<GI_Subject>{title}</GI_Subject><GI_Part_No>1000236</GI_Part_No>'
            f'<GI_Career>3</GI_Career><GI_Job_Type>{job_type}</GI_Job_Type><AreaCode>{area}</AreaCode>'
            f'<GI_End_Date>{end_date}</GI_End_Date><JK_URL>{jk_url}</JK_URL>'
            f'<GI_W_Date>{w_date}</GI_W_Date><GI_E_Date>{w_date}</GI_E_Date>{extra}</Items>')


def page(items, *, total=None, encoding='euc-kr', with_total=True):
    """One DataList response as bytes in ``encoding`` (the API answers EUC-KR)."""
    total = len(items) if total is None else total
    body = (f'<?xml version="1.0" encoding="{encoding}" ?>\n<DataList>'
            + (f'<TotalSumCnt>{total}</TotalSumCnt>' if with_total else '')
            + f'<TotalCnt>{len(items)}</TotalCnt>' + ''.join(items) + '</DataList>')
    return body.encode('cp949' if encoding.lower() == 'euc-kr' else encoding)
