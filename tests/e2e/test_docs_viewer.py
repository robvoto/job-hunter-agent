from playwright.sync_api import expect


def test_authenticated_user_guide_renders(candidate_page):
    page = candidate_page
    response = page.goto('/docs/view?doc=docs/USER_GUIDE.md')
    assert response is not None
    assert response.status == 200
    expect(page.locator('.header h1')).to_have_text('User Guide')
    output = page.locator('#md-output')
    expect(output).to_contain_text('Onboarding')
