import { store } from '../../store/appState';
import { USER_CATEGORIES, UserCategoryConfig, UserCategoryKey } from '../../types/userCategory';
import { ICONS } from '../../utils/icons';

export class CategoryModal {
  private element: HTMLElement;
  private selectedCategoryKey: UserCategoryKey = 'general_user';

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'modal-backdrop category-modal-backdrop';
    this.element.id = 'category-modal-backdrop';
    this.render();
    store.subscribe(() => this.updateVisibility());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private updateVisibility(): void {
    if (store.categoryModalOpen && store.currentUser) {
      if (store.userCategory?.category) {
        this.selectedCategoryKey = store.userCategory.category;
      }
      this.element.classList.add('active');
      this.render();
    } else {
      this.element.classList.remove('active');
    }
  }

  private render(): void {
    const isMandatory = !store.userCategory;
    const currentCategory = USER_CATEGORIES.find(c => c.key === this.selectedCategoryKey) || USER_CATEGORIES[0];

    this.element.innerHTML = `
      <div class="modal-container category-modal-card" style="max-width: 680px; width: 92%;">
        <div class="modal-header">
          <div style="font-weight:700;font-size:14px;color:var(--primary);display:flex;align-items:center;gap:8px;letter-spacing:0.04em;text-transform:uppercase;">
            <span>⚓</span>
            <span>Maritime Role &amp; Operational Profile</span>
          </div>
          ${!isMandatory ? `
            <button class="icon-btn" id="btn-close-category-modal" title="Close" aria-label="Close Role Selection Modal">
              ${ICONS.x}
            </button>
          ` : ''}
        </div>

        <div class="modal-body category-modal-body">
          <div class="category-hero-intro">
            <h3 class="category-modal-heading">
              ${isMandatory ? 'Select Your Maritime Operational Role' : 'Switch Your Maritime Profile'}
            </h3>
            <p class="category-modal-subtext">
              ORCA customizes multi-agent reasoning, INCOIS PFZ alerts, wave/wind safety floor thresholds, and SAR monitoring specific to your maritime operational category.
            </p>
          </div>

          <!-- Role Selection Grid -->
          <div class="category-grid" role="radiogroup" aria-label="Select your operational category">
            ${USER_CATEGORIES.map(cat => this.renderCategoryCard(cat, cat.key === this.selectedCategoryKey)).join('')}
          </div>

          <!-- Active Selection Summary Callout -->
          <div class="category-active-summary">
            <div class="summary-top">
              <span class="summary-icon">${currentCategory.icon}</span>
              <div>
                <strong class="summary-name">${currentCategory.name}</strong>
                <span class="summary-vessel-badge">${currentCategory.vesselLabel}</span>
              </div>
            </div>
            <p class="summary-desc">${currentCategory.description}</p>
            <div class="summary-focus-tags">
              ${currentCategory.focusBadges.map(b => `<span class="focus-pill">✓ ${b}</span>`).join('')}
            </div>
          </div>

          <!-- Confirm Action -->
          <button class="btn-confirm-category" id="btn-confirm-category">
            <span>Confirm Role &amp; Launch ORCA Console</span>
            <span>➔</span>
          </button>
        </div>
      </div>
    `;

    this.attachEvents();
  }

  private renderCategoryCard(cat: UserCategoryConfig, isSelected: boolean): string {
    return `
      <div class="category-card ${isSelected ? 'selected' : ''}" 
           data-key="${cat.key}" 
           role="radio" 
           aria-checked="${isSelected}"
           tabindex="0">
        <div class="category-card-header">
          <span class="category-card-icon">${cat.icon}</span>
          <div class="category-radio-indicator"></div>
        </div>
        <div class="category-card-title">${cat.name}</div>
        <div class="category-vessel-tag">${cat.vesselClass.replace(/_/g, ' ')}</div>
      </div>
    `;
  }

  private attachEvents(): void {
    // Category card click selection
    this.element.querySelectorAll('.category-card').forEach(card => {
      card.addEventListener('click', () => {
        const key = card.getAttribute('data-key') as UserCategoryKey;
        if (key && key !== this.selectedCategoryKey) {
          this.selectedCategoryKey = key;
          this.render();
        }
      });
    });

    // Close button (only when not mandatory)
    this.element.querySelector('#btn-close-category-modal')?.addEventListener('click', () => {
      if (store.userCategory) {
        store.toggleCategoryModal(false);
      }
    });

    // Backdrop click dismisses only if user already has a saved category
    this.element.addEventListener('click', (e) => {
      if (e.target === this.element && store.userCategory) {
        store.toggleCategoryModal(false);
      }
    });

    // Confirm button
    this.element.querySelector('#btn-confirm-category')?.addEventListener('click', async () => {
      const selected = USER_CATEGORIES.find(c => c.key === this.selectedCategoryKey) || USER_CATEGORIES[0];
      await store.setUserCategory(selected);
    });
  }
}
