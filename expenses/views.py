from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import Sum, Count
from datetime import date
import calendar
from django.conf import settings
from django.db import models  # Add this for the Q object
from .models import Expense, Budget
import csv
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from io import BytesIO
from .models import Expense, Budget, Category

# Home page with demo credentials
def home(request):
    return render(request, 'expenses/home.html', {
        'demo_username': settings.DEMO_USERNAME,
        'demo_password': settings.DEMO_PASSWORD,
    })

# Login view
def login_view(request):
    if request.user.is_authenticated:
        return redirect('expense_list')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {username}!')
            return redirect('expense_list')
        else:
            messages.error(request, 'Invalid username or password!')
    
    return render(request, 'expenses/login.html', {
        'demo_username': settings.DEMO_USERNAME,
        'demo_password': settings.DEMO_PASSWORD,
    })

# Register view
def register_view(request):
    if request.user.is_authenticated:
        return redirect('expense_list')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')
        email = request.POST.get('email', '')
        
        if password != password2:
            messages.error(request, 'Passwords do not match!')
            return render(request, 'expenses/register.html')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists!')
            return render(request, 'expenses/register.html')
        
        user = User.objects.create_user(username=username, email=email, password=password)
        messages.success(request, 'Account created successfully! Please login.')
        return redirect('login')
    
    return render(request, 'expenses/register.html')

# Logout view
def logout_view(request):
    logout(request)
    messages.success(request, 'Logged out successfully!')
    return redirect('login')

@login_required
def yearly_dashboard(request):
    # Get current year or selected year
    selected_year = request.GET.get('year', date.today().year)
    try:
        selected_year = int(selected_year)
    except ValueError:
        selected_year = date.today().year
    
    # Get all expenses for the user
    user_expenses = Expense.objects.filter(user=request.user)
    
    # Get available years - UNLIMITED: from oldest expense to 2 years in future
    current_year = date.today().year
    
    # Get the oldest and newest expense years
    oldest_expense = user_expenses.order_by('date').first()
    newest_expense = user_expenses.order_by('-date').first()
    
    if oldest_expense and newest_expense:
        oldest_year = oldest_expense.date.year
        newest_year = newest_expense.date.year
        # Start from oldest year, go up to max(current_year + 2, newest_year + 1)
        end_year = max(current_year + 2, newest_year + 1)
    else:
        oldest_year = current_year - 1
        end_year = current_year + 2
    
    # Create range from oldest year to end_year
    available_years = list(range(oldest_year, end_year + 1))
    available_years = sorted(set(available_years), reverse=True)
    
    # If no expenses, at least show current year and next 2 years
    if not available_years:
        available_years = [current_year + 2, current_year + 1, current_year, current_year - 1]
        available_years = sorted(set(available_years), reverse=True)
    
    # Get expenses for selected year
    year_expenses = user_expenses.filter(date__year=selected_year)
    
    # Monthly data for the year
    monthly_labels = []
    monthly_data = []
    
    for month in range(1, 13):
        month_total = year_expenses.filter(date__month=month).aggregate(Sum('amount'))['amount__sum'] or 0
        monthly_labels.append(calendar.month_abbr[month])
        monthly_data.append(float(month_total))
    
    # Category-wise spending for the year - FIXED WITH EMPTY FALLBACKS
    category_data = year_expenses.values('category__id', 'category__name', 'category__color').annotate(
        total=Sum('amount')
    ).order_by('-total')

    categories = []
    category_totals = []
    colors = []

    for item in category_data:
        cat_name = item['category__name'] or 'Uncategorized'
        categories.append(cat_name)
        category_totals.append(float(item['total']))
        color = item['category__color'] or '#6c757d'
        colors.append(color)

    if not categories:
        categories = ['No Data']
        category_totals = [0]  # Fixed: Given fallback array value
        colors = ['#6c757d']
    
    # Summary statistics
    total_expenses = year_expenses.count()
    total_amount = year_expenses.aggregate(Sum('amount'))['amount__sum'] or 0
    avg_monthly = total_amount / 12 if total_expenses > 0 else 0
    
    # Find highest month
    highest_month = max(monthly_data) if monthly_data else 0
    
    # Create month list with data
    month_list = []
    for month in range(1, 13):
        month_list.append({
            'month_num': month,
            'month_name': calendar.month_name[month],
            'amount': monthly_data[month - 1],
            'has_data': monthly_data[month - 1] > 0
        })
    
    context = {
        'selected_year': selected_year,
        'available_years': available_years,
        'monthly_labels': monthly_labels,
        'monthly_data': monthly_data,
        'categories': categories,
        'category_totals': category_totals,
        'category_colors': colors,
        'total_expenses': total_expenses,
        'total_amount': total_amount,
        'avg_monthly': avg_monthly,
        'highest_month': highest_month,
        'month_list': month_list,
    }
    return render(request, 'expenses/yearly_dashboard.html', context)


@login_required
def monthly_dashboard(request, year, month):
    user_expenses = Expense.objects.filter(user=request.user, date__year=year, date__month=month)
    
    # Monthly spending for last 6 months (for trend chart)
    monthly_labels = []
    monthly_data = []
    
    for i in range(5, -1, -1):
        m = month - i
        y = year
        if m <= 0:
            m += 12
            y -= 1
        elif m > 12:
            m -= 12
            y += 1
        
        month_total = Expense.objects.filter(
            user=request.user,
            date__year=y,
            date__month=m
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        monthly_labels.append(calendar.month_abbr[m])
        monthly_data.append(float(month_total))
    
    # Category-wise spending
    category_data = user_expenses.values('category__id', 'category__name', 'category__color').annotate(
        total=Sum('amount')
    ).order_by('-total')
    
    categories = []
    category_totals = []
    colors = []
    
    for item in category_data:
        cat_name = item['category__name'] or 'Uncategorized'
        categories.append(cat_name)
        category_totals.append(float(item['total']))
        color = item['category__color'] or '#6c757d'
        colors.append(color)
    
    if not categories:
        categories = ['No Data']
        category_totals = [0]
        colors = ['#6c757d']
    
    total_amount = user_expenses.aggregate(Sum('amount'))['amount__sum'] or 0
    total_expenses = user_expenses.count()
    
    context = {
        'year': year,
        'month': month,
        'month_name': calendar.month_name[month],
        'expenses': user_expenses,
        'categories': categories,
        'category_totals': category_totals,
        'category_colors': colors,
        'total_amount': total_amount,
        'total_expenses': total_expenses,
        # Add these for the trend chart
        'monthly_labels': monthly_labels,
        'monthly_data': monthly_data,
    }
    
    return render(request, 'expenses/monthly_dashboard.html', context)


# Expense List
@login_required
def expense_list(request):
    # Get all expenses for the user
    expenses = Expense.objects.filter(user=request.user)
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        expenses = expenses.filter(
            models.Q(title__icontains=search_query) | 
            models.Q(description__icontains=search_query)
        )
    
    # Filter by category
    category_filter = request.GET.get('category', '')
    if category_filter:
        expenses = expenses.filter(category_id=category_filter)
    
    # Filter by date range
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if date_from:
        expenses = expenses.filter(date__gte=date_from)
    if date_to:
        expenses = expenses.filter(date__lte=date_to)
    
    # Order by date (newest first)
    expenses = expenses.order_by('-date')
    
    # Calculate total
    total = sum(expense.amount for expense in expenses)
    
    # Get all categories for the filter dropdown
    categories = Category.objects.filter(user=request.user)
    
    context = {
        'expenses': expenses,
        'total': total,
        'username': request.user.username,
        'search_query': search_query,
        'category_filter': category_filter,
        'date_from': date_from,
        'date_to': date_to,
        'categories': categories,
        'total_count': expenses.count(),
    }
    
    return render(request, 'expenses/list.html', context)

# Add Expense (Protected)
@login_required
def add_expense(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        amount = request.POST.get('amount')
        category_id = request.POST.get('category')
        description = request.POST.get('description')
        expense_date = request.POST.get('date')
        next_url = request.POST.get('next', '')
        
        if not expense_date:
            expense_date = date.today()
        
        # Get the category object
        category = None
        if category_id:
            try:
                category = Category.objects.get(id=category_id, user=request.user)
            except Category.DoesNotExist:
                pass
        
        Expense.objects.create(
            user=request.user,
            title=title,
            amount=amount,
            category=category,
            description=description,
            date=expense_date
        )
        messages.success(request, 'Expense added successfully!')
        
        if next_url:
            return redirect(next_url)
        return redirect('expense_list')
    
    categories = Category.objects.filter(user=request.user)
    next_url = request.GET.get('next', '')
    return render(request, 'expenses/add.html', {
        'today': date.today(), 
        'next': next_url,
        'categories': categories
    })

# Edit Expense (Protected)
@login_required
def edit_expense(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    
    if request.method == 'POST':
        expense.title = request.POST.get('title')
        expense.amount = request.POST.get('amount')
        category_id = request.POST.get('category')
        expense.description = request.POST.get('description')
        expense_date = request.POST.get('date')
        next_url = request.POST.get('next', '')
        
        if expense_date:
            expense.date = expense_date
        
        # Update category
        if category_id:
            try:
                expense.category = Category.objects.get(id=category_id, user=request.user)
            except Category.DoesNotExist:
                expense.category = None
        else:
            expense.category = None
        
        expense.save()
        messages.success(request, 'Expense updated successfully!')
        
        if next_url:
            return redirect(next_url)
        return redirect('expense_list')
    
    categories = Category.objects.filter(user=request.user)
    next_url = request.GET.get('next', '')
    return render(request, 'expenses/edit.html', {
        'expense': expense, 
        'next': next_url,
        'categories': categories
    })

# Delete Expense (Protected)
@login_required
def delete_expense(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    if request.method == 'POST':
        expense.delete()
        messages.success(request, 'Expense deleted successfully!')
        next_url = request.POST.get('next', '')
        if next_url:
            return redirect(next_url)
        return redirect('expense_list')
    
    next_url = request.GET.get('next', '')
    return render(request, 'expenses/delete.html', {'expense': expense, 'next': next_url})

# Change Password
@login_required
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(request, 'Password changed successfully!')
            return redirect('dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PasswordChangeForm(user=request.user)
    
    return render(request, 'expenses/change_password.html', {'form': form})

# Update Profile
@login_required
def update_profile(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        
        user = request.user
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.save()
        
        messages.success(request, 'Profile updated successfully!')
        return redirect('dashboard')
    
    return render(request, 'expenses/update_profile.html', {'user': request.user})

# Set Budget
@login_required
def set_budget(request):
    budget, created = Budget.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        monthly_budget = request.POST.get('monthly_budget')
        if monthly_budget:
            budget.monthly_budget = monthly_budget
            budget.save()
            messages.success(request, f'Budget set to ₹{monthly_budget}')
            return redirect('dashboard')
    
    return render(request, 'expenses/set_budget.html', {'budget': budget})


# Dashboard
@login_required
def dashboard(request):
    # Get current month and year
    today = date.today()
    current_month = today.month
    current_year = today.year
    
    # Get all expenses for the user
    user_expenses = Expense.objects.filter(user=request.user)
    
    # Monthly spending for last 6 months
    monthly_labels = []
    monthly_data = []
    
    for i in range(5, -1, -1):
        month = today.month - i
        year = today.year
        if month <= 0:
            month += 12
            year -= 1
        
        month_total = user_expenses.filter(
            date__month=month,
            date__year=year
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        monthly_labels.append(calendar.month_abbr[month])
        monthly_data.append(float(month_total))
    
    # Category-wise spending
    category_data = user_expenses.values('category__id', 'category__name', 'category__color').annotate(
        total=Sum('amount')
    ).order_by('-total')
    
    categories = []
    category_totals = []
    colors = []
    
    for item in category_data:
        cat_name = item['category__name'] or 'Uncategorized'
        categories.append(cat_name)
        category_totals.append(float(item['total']))
        color = item['category__color'] or '#6c757d'
        colors.append(color)
    
    # If no categories with data, use default
    if not categories:
        categories = ['No Data']
        category_totals = [0]
        colors = ['#6c757d']
    
    # Summary statistics
    total_expenses = user_expenses.count()
    total_amount = user_expenses.aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Current month total
    current_month_total = user_expenses.filter(
        date__month=current_month,
        date__year=current_year
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Today's expenses
    today_total = user_expenses.filter(date=today).aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Recent expenses
    recent_expenses = user_expenses.order_by('-date')[:5]
    
    # Get or create budget
    budget, created = Budget.objects.get_or_create(user=request.user)
    monthly_budget = float(budget.monthly_budget)
    
    # Calculate budget percentage
    budget_percentage = 0
    budget_remaining = monthly_budget
    if monthly_budget > 0:
        budget_percentage = min((float(current_month_total) / monthly_budget) * 100, 100)
        budget_remaining = monthly_budget - float(current_month_total)
    
    context = {
        'monthly_labels': monthly_labels,
        'monthly_data': monthly_data,
        'categories': categories,
        'category_totals': category_totals,
        'category_colors': colors,
        'total_expenses': total_expenses,
        'total_amount': total_amount,
        'current_month_total': current_month_total,
        'today_total': today_total,
        'today': today,
        'expenses': recent_expenses,
        'username': request.user.username,
        'monthly_budget': monthly_budget,
        'budget_percentage': round(budget_percentage, 1),
        'budget_remaining': budget_remaining,
        'is_over_budget': budget_remaining < 0,
    }
    
    return render(request, 'expenses/dashboard.html', context)
#CSV
@login_required
def export_csv(request):
    # Get filter parameters
    category = request.GET.get('category', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    year = request.GET.get('year', '')
    month = request.GET.get('month', '')
    
    # Get expenses
    expenses = Expense.objects.filter(user=request.user)
    
    if category:
        expenses = expenses.filter(category_id=category)
    if date_from:
        expenses = expenses.filter(date__gte=date_from)
    if date_to:
        expenses = expenses.filter(date__lte=date_to)
    if year:
        expenses = expenses.filter(date__year=year)
    if month:
        expenses = expenses.filter(date__month=month)
    
    expenses = expenses.order_by('-date')
    
    # Create filename
    filename = "expenses"
    if year and month:
        # Convert month to int for formatting
        try:
            month_int = int(month)
            filename = f"expenses_{year}_{month_int:02d}"
        except ValueError:
            filename = f"expenses_{year}_{month}"
    elif year:
        filename = f"expenses_{year}"
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Title', 'Amount', 'Category', 'Date', 'Description'])
    
    for expense in expenses:
        writer.writerow([
            expense.title,
            float(expense.amount),
            expense.category.name if expense.category else 'Uncategorized',
            expense.date.strftime('%Y-%m-%d'),
            expense.description or ''
        ])
    
    return response

#PDF
@login_required
def export_pdf(request):
    # Get filter parameters
    category = request.GET.get('category', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    year = request.GET.get('year', '')
    month = request.GET.get('month', '')
    
    # Get expenses
    expenses = Expense.objects.filter(user=request.user)
    
    if category:
        expenses = expenses.filter(category_id=category)
    if date_from:
        expenses = expenses.filter(date__gte=date_from)
    if date_to:
        expenses = expenses.filter(date__lte=date_to)
    if year:
        expenses = expenses.filter(date__year=year)
    if month:
        expenses = expenses.filter(date__month=month)
    
    expenses = expenses.order_by('-date')
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#333333'),
        spaceAfter=10
    )
    
    # Content
    story = []
    
    # Title
    title_text = "Expense Report"
    if year and month:
        title_text = f"Expense Report - {calendar.month_name[int(month)]} {year}"
    elif year:
        title_text = f"Expense Report - {year}"
    
    story.append(Paragraph(title_text, title_style))
    story.append(Paragraph(f"Generated on: {date.today().strftime('%B %d, %Y')}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Summary
    total_amount = sum(expense.amount for expense in expenses)
    story.append(Paragraph(f"Total Expenses: ₹{float(total_amount):,.2f}", heading_style))
    story.append(Paragraph(f"Total Transactions: {expenses.count()}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Table data
    table_data = [['#', 'Title', 'Amount (₹)', 'Category', 'Date']]
    for idx, expense in enumerate(expenses[:50], 1):
        table_data.append([
            str(idx),
            expense.title[:30],
            f"{float(expense.amount):,.2f}",
            expense.category.name if expense.category else 'Uncategorized',
            expense.date.strftime('%Y-%m-%d')
        ])
    
    # Table
    table = Table(table_data, colWidths=[40, 150, 100, 100, 100])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    
    story.append(table)
    
    # Footer
    story.append(Spacer(1, 30))
    story.append(Paragraph("Generated by Expense Tracker", styles['Normal']))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="expenses_{date.today().strftime("%Y-%m-%d")}.pdf"'
    return response

#Categories
@login_required
def manage_categories(request):
    categories = Category.objects.filter(user=request.user)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add':
            name = request.POST.get('name')
            color = request.POST.get('color', '#6c757d')
            icon = request.POST.get('icon', 'bi-tag')
            
            if name:
                Category.objects.create(user=request.user, name=name, color=color, icon=icon)
                messages.success(request, f'Category "{name}" added successfully!')
        
        elif action == 'edit':
            category_id = request.POST.get('category_id')
            name = request.POST.get('name')
            color = request.POST.get('color')
            icon = request.POST.get('icon')
            
            try:
                category = Category.objects.get(id=category_id, user=request.user)
                if name:
                    category.name = name
                if color:
                    category.color = color
                if icon:
                    category.icon = icon
                category.save()
                messages.success(request, 'Category updated successfully!')
            except Category.DoesNotExist:
                messages.error(request, 'Category not found!')
        
        elif action == 'delete':
            category_id = request.POST.get('category_id')
            try:
                category = Category.objects.get(id=category_id, user=request.user)
                category.delete()
                messages.success(request, 'Category deleted successfully!')
            except Category.DoesNotExist:
                messages.error(request, 'Category not found!')
        
        return redirect('manage_categories')
    
    return render(request, 'expenses/manage_categories.html', {'categories': categories})